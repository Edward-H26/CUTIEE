"""Computer Use runner, the single agent loop in CUTIEE.

Drives a screenshot to function-call loop against any `CuClient`
Protocol implementation: `GeminiComputerUseClient` at
`gemini-flash-latest` by default, or `BrowserUseClient` wrapping
`browser_use.Agent` with Gemini 3 Flash as the fixed LLM.

Responsibilities:
  - pre-run preview: surface a natural-language summary for user
    approval before any browser action fires (Phase 16).
  - replay: whole-template replay, hybrid prematched replay, and
    fragment-level interleaved replay (Phase 15).
  - model loop: screenshot, safety guards (injection, CAPTCHA),
    cost caps, wall-clock heartbeat, approval gate, action execute,
    redaction, screenshot persist, audit write.
  - memory writeback at end of run (Reflector then Gate then Curator
    then Apply then Refine), only after the entire run terminates.

Every guard is optional: the runner keeps its pre-phase behavior when
the corresponding field is None or absent.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..browser.controller import BrowserController, BrowserControllerProtocol, StepResult
from .state import (
    Action,
    ActionType,
    AgentState,
    ObservationStep,
    RiskLevel,
)
from ..routing.cu_client import CuClient
from ..routing.models.gemini_cu import GeminiComputerUseClient
from ..safety.approval_gate import ApprovalGate
from ..safety.audit import AuditPayload, buildAuditPayload
from ..safety.risk_classifier import classifyRisk

logger = logging.getLogger("cutiee.cu_runner")

ProgressCb = Callable[[AgentState, ObservationStep], Awaitable[None] | None]
AuditCb = Callable[[AuditPayload], Awaitable[None] | None]
ScreenshotSink = Callable[[str, int, bytes], Awaitable[None] | None]

# URL substrings that indicate the agent landed on a sign-in flow when the
# user expected to be on a logged-in surface. Surfacing this as a clear
# "auth_expired" completion reason saves users from chasing phantom bugs.
AUTH_REDIRECT_HINTS = (
    "accounts.google.com/signin",
    "accounts.google.com/v3/signin",
    "login.live.com",
    "github.com/login",
    "auth0.com/u/login",
)


@dataclass
class ComputerUseRunner:
    browser: BrowserControllerProtocol
    client: CuClient
    approvalGate: ApprovalGate
    onProgress: ProgressCb | None = None
    auditSink: AuditCb | None = None
    screenshotSink: ScreenshotSink | None = None
    memory: Any | None = None  # ACEPipeline; processExecution(state) called at end
    replayPlanner: Any | None = None  # ReplayPlanner; findReplayPlan(task, userId)
    initialUrl: str = ""
    maxSteps: int = 20
    maxRetriesPerStep: int = 1
    # Pre-matched ActionNodes from subgraph matcher (hybrid replay prefix).
    prematchedNodes: list = field(default_factory = list)
    # Phase 15 fragment-level replay. When set, the runner calls the
    # matcher after browser.start and interleaves matched fragments
    # with the model loop per step index.
    fragmentMatcher: Any | None = None  # callable(taskDescription, userId) -> FragmentPlan
    # Phase 16 pre-run preview. When set, the runner surfaces a
    # natural-language summary through Neo4j and blocks until the
    # user approves or cancels. `previewTimeoutSeconds` bounds the
    # wait so a broken dashboard cannot hang a worker forever; the
    # timeout resolves as cancellation because consent cannot be
    # assumed in the absence of a response.
    previewHook: Any | None = None  # async callable(state, summary) -> PreviewOutcome | None
    previewTimeoutSeconds: float = 600.0  # 10 minutes
    # Phase 4 wallet cap. When set, the runner checks per-task,
    # per-hour, and per-day ledgers and exits cleanly on breach.
    maxCostUsdPerTask: float = 0.0  # 0 disables
    maxCostUsdPerHour: float = 0.0  # 0 disables
    maxCostUsdPerDay: float = 0.0  # 0 disables
    # Phase 7 wall-clock heartbeat tracker. Tracks silent intervals.
    heartbeat: Any | None = None
    # Phase 5 injection guard and Phase 6 CAPTCHA detector run before
    # every model call; either may flip a terminal completion reason.
    injectionGuard: Any | None = None
    captchaDetector: Any | None = None
    # Phase 8 screenshot redactor runs before the screenshot sink.
    redactor: Any | None = None

    async def run(
        self,
        *,
        userId: str,
        taskId: str | None,
        taskDescription: str,
        executionId: str | None = None,
    ) -> AgentState:
        state = AgentState(
            taskId = taskId or str(uuid.uuid4()),
            userId = userId,
            taskDescription = taskDescription,
        )
        if executionId:
            state.executionId = executionId

        # Phase 15: compute a fragment plan before preview so the preview
        # can tell the user how many steps replay for free.
        fragmentPlan = await self._resolveFragmentPlan(userId, taskDescription)

        # Phase 16: surface the approach to the user and block on approval.
        if not await self._runPreviewAndAwaitApproval(state, fragmentPlan):
            return state  # cancelled; nothing else to do

        await self.browser.start()
        try:
            # Whole-template replay wins first (cheapest path).
            replayPlan = None
            if self.replayPlanner is not None:
                replayPlan = await _maybe(
                    self.replayPlanner.findReplayPlan(taskDescription, userId)
                )

            if replayPlan is not None:
                await self._executeReplay(state, replayPlan)
                state.replayed = True
            else:
                # Hybrid prematched replay (whole prefix) takes priority
                # over fragment replay when both are available.
                if self.prematchedNodes:
                    await self._executePrematchedNodes(state)
                elif self.initialUrl:
                    await self._recordInitialNavigation(state)
                if not state.isComplete:
                    await self._runLoop(state, fragmentPlan = fragmentPlan)
        finally:
            await self.browser.stop()

        if not state.isComplete:
            state.markComplete("max_steps_reached")

        # Memory writeback runs ONLY after the full run terminates.
        # Skipped for pure replay runs because the source bullets already
        # encode the lesson; a fragment-mixed run still writes back so
        # the reflector can capture the dynamic-value steps.
        if self.memory is not None and not state.replayed:
            await _maybe(self.memory.processExecution(state))

        return state

    async def _resolveFragmentPlan(self, userId: str, taskDescription: str) -> Any:
        if self.fragmentMatcher is None:
            return None
        try:
            plan = self.fragmentMatcher(taskDescription = taskDescription, userId = userId)
            return await _maybe(plan)
        except Exception as exc:  # noqa: BLE001 - matcher errors must not kill the run
            logger.warning("Fragment matcher failed: %r", exc)
            return None

    async def _runPreviewAndAwaitApproval(self, state: AgentState, fragmentPlan: Any) -> bool:
        if self.previewHook is None:
            return True
        # Cap the preview wait at `previewTimeoutSeconds` so a broken
        # dashboard cannot hang the runner thread forever. Timeout
        # resolves as "cancelled" by default because consent cannot
        # be assumed in the absence of a response.
        try:
            coro = _maybe(self.previewHook(state, fragmentPlan))
            outcome = await asyncio.wait_for(
                coro,
                timeout = max(1.0, float(self.previewTimeoutSeconds)),
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Preview approval timed out after %ss; treating as cancelled",
                self.previewTimeoutSeconds,
            )
            state.markComplete("preview_timeout")
            return False
        except Exception as exc:  # noqa: BLE001 - preview failures must not block
            logger.warning("Preview hook failed, skipping preview: %r", exc)
            return True
        if outcome is None:
            return True
        status = getattr(outcome, "status", "approved")
        if status == "cancelled":
            state.markComplete("user_cancelled_preview")
            return False
        return True

    async def _executePrematchedNodes(self, state: AgentState) -> None:
        """Execute the subgraph-matcher's pre-matched prefix at zero cost,
        with Phase 4 state verification before each replay.

        Each pre-matched ActionNode becomes an Action with tier=0,
        cost_usd=0, model_used="replay-graph". Before executing, the
        StateVerifier compares current URL + screenshot phash to the
        node's recorded `expected_url` / `expected_phash`. If verification
        fails, the runner stops replay and falls through to the model
        loop — better to pay one extra Gemini call than to click the
        wrong thing.
        """
        from ..memory.state_verifier import StateVerifier
        verifier = StateVerifier()

        for offset, node in enumerate(self.prematchedNodes):
            # Convert ActionNode → Action
            try:
                actionType = ActionType(node.action_type)
            except ValueError:
                logger.warning("Skipping pre-matched node with unknown type: %s", node.action_type)
                continue

            # Phase 4 state verification (skipped for the very first node since
            # it always runs against the initial page state; verifier handles
            # missing expected_* fields gracefully).
            try:
                currentUrl = await self.browser.currentUrl()
                currentScreenshot = await self.browser.captureScreenshot()
            except Exception:  # noqa: BLE001 - browser hiccups don't block run
                currentUrl = ""
                currentScreenshot = b""

            verification = verifier.verify(
                node = node,
                currentUrl = currentUrl,
                currentScreenshot = currentScreenshot,
            )
            if not verification.safe:
                logger.info(
                    "Replay halt at offset %d: verification failed (%s); falling through to model",
                    offset, verification.reason,
                )
                return

            coord = None
            if node.coord_x is not None and node.coord_y is not None:
                coord = (int(node.coord_x), int(node.coord_y))

            action = Action(
                type = actionType,
                target = node.target or "",
                value = node.value or None,
                coordinate = coord,
                reasoning = f"replay-graph: {node.description} ({verification.reason})" if node.description else f"graph-replay ({verification.reason})",
                model_used = "replay-graph",
                tier = 0,
                confidence = 1.0,
                cost_usd = 0.0,
            )
            action.risk = classifyRisk(action, state.taskDescription)
            action.requires_approval = action.risk == RiskLevel.HIGH

            approvalStatus = "auto"
            if action.requires_approval:
                approved = await self.approvalGate.requestApproval(action)
                approvalStatus = "approved" if approved else "rejected"
                if not approved:
                    state.markComplete("rejected_by_user_graph_replay")
                    return

            result = await self.browser.execute(action)
            currentUrl = await self.browser.currentUrl()
            step = ObservationStep(
                index = state.stepCount(),
                url = currentUrl,
                action = action,
                verificationOk = result.success,
                verificationNote = result.detail,
                durationMs = result.durationMs,
            )
            state.appendStep(step)
            await self._emitProgress(state, step)
            await self._writeAudit(state, step, approvalStatus)

            if not result.success:
                logger.info(
                    "Pre-matched replay failed at step %d (%s); falling through to model",
                    offset, result.detail,
                )
                return

        logger.info(
            "Hybrid replay: executed %d pre-matched nodes at $0; continuing with model",
            len(self.prematchedNodes),
        )

    async def _executeReplay(self, state: AgentState, plan: Any) -> None:
        """Run a memorized template at zero inference cost."""
        baseIndex = state.stepCount()
        for offset, action in enumerate(getattr(plan, "actions", [])):
            action.cost_usd = 0.0
            action.tier = 0
            action.model_used = "replay"
            action.risk = classifyRisk(action, state.taskDescription)
            action.requires_approval = action.requires_approval or action.risk.value == "high"

            approvalStatus = "auto"
            if action.requires_approval:
                approved = await self.approvalGate.requestApproval(action)
                approvalStatus = "approved" if approved else "rejected"
                if not approved:
                    state.markComplete("rejected_by_user_replay")
                    return

            result = await self.browser.execute(action)
            currentUrl = await self.browser.currentUrl()
            step = ObservationStep(
                index = baseIndex + offset,
                url = currentUrl,
                action = action,
                verificationOk = result.success,
                verificationNote = result.detail,
                durationMs = result.durationMs,
            )
            state.appendStep(step)
            await self._emitProgress(state, step)
            await self._writeAudit(state, step, approvalStatus)

            if not result.success:
                state.markComplete("replay_failed")
                return

        state.markComplete("replay_success")

    async def _recordInitialNavigation(self, state: AgentState) -> None:
        action = Action(
            type = ActionType.NAVIGATE,
            target = self.initialUrl,
            reasoning = "initial navigation",
            model_used = "harness",
            tier = 0,
            confidence = 1.0,
        )
        action.risk = classifyRisk(action, state.taskDescription)
        result = await self.browser.execute(action)
        step = ObservationStep(
            index = state.stepCount(),
            url = self.initialUrl,
            action = action,
            verificationOk = result.success,
            verificationNote = result.detail,
            durationMs = result.durationMs,
        )
        state.appendStep(step)
        await self._emitProgress(state, step)
        await self._writeAudit(state, step, approvalStatus = "auto")
        try:
            png = await self.browser.captureScreenshot()
        except Exception:  # noqa: BLE001 - capture failures don't block the run
            png = b""
        if png:
            await self._dispatchScreenshot(state.executionId, step.index, png)

    async def _runLoop(self, state: AgentState, fragmentPlan: Any = None) -> None:
        screenshot = await self.browser.captureScreenshot()
        currentUrl = await self.browser.currentUrl()
        self.client.primeTask(state.taskDescription, currentUrl)

        # Auth-expired detection: if we navigated to a logged-in URL but
        # ended up on a sign-in page, surface a clear completion reason
        # instead of letting the agent click around the login form.
        if self.initialUrl and _looksLikeAuthRedirect(self.initialUrl, currentUrl):
            state.markComplete(
                "auth_expired:re-run scripts/capture_storage_state.py "
                "or set CUTIEE_BROWSER_CDP_URL to attach to a signed-in Chrome"
            )
            return

        for stepIndex in range(state.stepCount(), self.maxSteps):
            # Phase 15 fragment interleave: when a fragment matches this
            # step index and does not require a dynamic model value, we
            # dispatch it directly at zero cost. Fragments requiring a
            # model-supplied value fall through to the model call so the
            # coordinate replays but the value stays dynamic.
            fragment = self._fragmentForStep(fragmentPlan, stepIndex)
            if fragment is not None and not fragment.requires_model_value:
                # Phase 17 plan-drift detection: before executing a
                # replay fragment, check that the current page matches
                # the fragment's expected state. A divergence triggers
                # a fresh preview approval; the user decides whether
                # to continue with the revised plan or cancel.
                driftDecision = await self._handlePlanDrift(
                    state = state,
                    stepIndex = stepIndex,
                    fragment = fragment,
                    currentUrl = currentUrl,
                )
                if driftDecision == "cancelled":
                    return
                if driftDecision == "abandon_fragment":
                    # Fall through to the model loop for this step only.
                    pass
                else:
                    step, stepResult = await self._executeFragment(state, stepIndex, fragment)
                    if step is None:
                        return
                    screenshot = await self.browser.captureScreenshot()
                    currentUrl = await self.browser.currentUrl()
                    if step.action and step.action.type == ActionType.FINISH:
                        state.markComplete(step.action.reasoning or "finish_action")
                        return
                    if not stepResult.success:
                        state.markComplete(f"replay_fragment_failed:{stepResult.detail}")
                        return
                    continue

            step, stepResult, screenshot, currentUrl = await self._executeOneStepWithRetry(
                state = state,
                stepIndex = stepIndex,
                screenshot = screenshot,
                currentUrl = currentUrl,
            )

            if step is None:
                # Approval rejected OR a guard terminated the run.
                return

            if step.action and step.action.type == ActionType.FINISH:
                state.markComplete(step.action.reasoning or "finish_action")
                return

            if not stepResult.success:
                state.markComplete(f"action_failed:{stepResult.detail}")
                return

    def _fragmentForStep(self, fragmentPlan: Any, stepIndex: int) -> Any:
        if fragmentPlan is None:
            return None
        lookup = getattr(fragmentPlan, "fragmentForStep", None)
        if callable(lookup):
            return lookup(stepIndex)
        return None

    async def _executeFragment(
        self,
        state: AgentState,
        stepIndex: int,
        fragment: Any,
    ) -> tuple[ObservationStep | None, StepResult]:
        """Execute a Phase 15 replay fragment at zero cost.

        Fragments that match the current step index and carry a fully
        specified action (coordinate, action type, any non-dynamic
        values) replay straight through `browser.execute`. Approval
        still fires for HIGH-risk fragments, so a misfire is still
        gated by the same mechanism as a normal model step.
        """
        action = fragment.action
        action.tier = 0
        action.cost_usd = 0.0
        action.model_used = "fragment_replay"
        approvalStatus = "auto"
        if getattr(action, "requires_approval", False):
            approved = await self.approvalGate.requestApproval(action)
            approvalStatus = "approved" if approved else "rejected"
            if not approved:
                state.markComplete("rejected_by_user_fragment_replay")
                return None, _failed("rejected")

        result = await self.browser.execute(action)
        currentUrl = await self.browser.currentUrl()
        step = ObservationStep(
            index = stepIndex,
            url = currentUrl,
            domMarkdown = f"[fragment_replay] bullet={fragment.bullet_id[:8]} confidence={fragment.confidence:.2f}",
            action = action,
            verificationOk = result.success,
            verificationNote = result.detail,
            durationMs = result.durationMs,
        )
        state.appendStep(step)
        await self._emitProgress(state, step)
        await self._writeAudit(state, step, approvalStatus)
        return step, result

    async def _executeOneStepWithRetry(
        self,
        *,
        state: AgentState,
        stepIndex: int,
        screenshot: bytes,
        currentUrl: str,
    ) -> tuple[ObservationStep | None, StepResult, bytes, str]:
        """Run one model→browser step. On failure, retry once with a fresh screenshot.

        Captures exactly ONE screenshot per attempt: the post-action shot
        is broadcast to both the persistence sink and the next iteration
        so we don't pay for two captures per step.
        """
        attempts = 0
        while True:
            # Phase 6 CAPTCHA watchdog: fingerprint the screenshot BEFORE
            # spending a model call. When a CAPTCHA is detected we exit
            # cleanly so the user can solve the challenge in the browser.
            captchaHit = self._detectCaptcha(screenshot)
            if captchaHit is not None:
                state.markComplete(f"captcha_detected:{captchaHit}")
                return None, _failed(f"captcha:{captchaHit}"), screenshot, currentUrl

            # Phase 5 injection guard: annotate suspicious screenshots so
            # the approval gate knows to escalate the next action.
            injectionSuspected = self._scanForInjection(screenshot)

            cuStep = await self.client.nextAction(screenshot, currentUrl)
            action = cuStep.action
            action.tier = 1
            action.risk = classifyRisk(action, state.taskDescription)
            if injectionSuspected:
                action.risk = RiskLevel.HIGH
                action.reasoning = f"{action.reasoning} injection_suspected".strip()
            action.requires_approval = action.risk == RiskLevel.HIGH

            # Phase 4 wallet cap (per-task and Neo4j-backed per-hour).
            capHit = self._checkCostCaps(state, cuStep.costUsd)
            if capHit is not None:
                state.markComplete(f"cost_cap_reached:{capHit}")
                return None, _failed(f"cost_cap:{capHit}"), screenshot, currentUrl

            # Phase 7 wall-clock heartbeat.
            heartbeatHit = self._checkHeartbeat()
            if heartbeatHit is not None:
                state.markComplete(f"wallclock_heartbeat:{heartbeatHit}")
                return None, _failed(f"heartbeat:{heartbeatHit}"), screenshot, currentUrl

            approvalStatus = "auto"
            if action.requires_approval:
                approved = await self.approvalGate.requestApproval(action)
                approvalStatus = "approved" if approved else "rejected"
                if not approved:
                    state.markComplete("rejected_by_user")
                    return None, _failed("rejected"), screenshot, currentUrl

            stepResult = await self.browser.execute(action)
            currentUrl = await self.browser.currentUrl()
            step = ObservationStep(
                index = stepIndex,
                url = currentUrl,
                domMarkdown = (
                    f"[computer_use] fn={cuStep.rawFunctionName} "
                    f"args={cuStep.rawArgs} attempt={attempts}"
                ),
                action = action,
                verificationOk = stepResult.success,
                verificationNote = stepResult.detail,
                durationMs = stepResult.durationMs,
            )
            state.appendStep(step)
            await self._emitProgress(state, step)
            await self._writeAudit(state, step, approvalStatus)

            # Single capture; broadcast to sink + next-iteration input.
            rawScreenshot = await self.browser.captureScreenshot()
            screenshot = await self._redactForSink(rawScreenshot)
            await self._dispatchScreenshot(state.executionId, step.index, screenshot)

            if stepResult.success or attempts >= self.maxRetriesPerStep:
                return step, stepResult, screenshot, currentUrl

            logger.info(
                "CU step %s failed (%s); retrying with fresh screenshot (attempt %s)",
                stepIndex, stepResult.detail, attempts + 1,
            )
            attempts += 1

    async def _emitProgress(self, state: AgentState, step: ObservationStep) -> None:
        if self.onProgress is None:
            return
        result = self.onProgress(state, step)
        if asyncio.iscoroutine(result):
            await result

    async def _writeAudit(self, state: AgentState, step: ObservationStep, approvalStatus: str) -> None:
        if self.auditSink is None:
            return
        payload = buildAuditPayload(
            userId = state.userId,
            taskId = state.taskId,
            executionId = state.executionId,
            step = step,
            approvalStatus = approvalStatus,
        )
        result = self.auditSink(payload)
        if asyncio.iscoroutine(result):
            await result

    async def _dispatchScreenshot(self, executionId: str, stepIndex: int, png: bytes) -> None:
        """Best-effort send of an already-captured PNG to the persistence sink."""
        if self.screenshotSink is None:
            return
        try:
            result = self.screenshotSink(executionId, stepIndex, png)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001 - persistence is best-effort, run continues
            logger.debug("Screenshot persistence failed at step %s", stepIndex, exc_info = True)

    def _detectCaptcha(self, screenshot: bytes) -> str | None:
        if self.captchaDetector is None or not screenshot:
            return None
        try:
            result = self.captchaDetector(screenshot)
        except Exception:  # noqa: BLE001
            logger.debug("captcha_detector raised", exc_info = True)
            return None
        detected = getattr(result, "detected", False)
        if not detected:
            return None
        return getattr(result, "kind", "captcha")

    def _scanForInjection(self, screenshot: bytes) -> bool:
        if self.injectionGuard is None or not screenshot:
            return False
        try:
            result = self.injectionGuard(screenshot)
        except Exception:  # noqa: BLE001
            logger.debug("injection_guard raised", exc_info = True)
            return False
        return bool(getattr(result, "suspected", False))

    def _checkCostCaps(self, state: AgentState, projectedStepCost: float) -> str | None:
        projected = state.totalCostUsd + max(0.0, projectedStepCost)
        if self.maxCostUsdPerTask > 0 and projected > self.maxCostUsdPerTask:
            return "per_task"
        if self.maxCostUsdPerHour <= 0 and self.maxCostUsdPerDay <= 0:
            return None
        try:
            from agent.harness.cost_ledger import incrementAndCheck
        except ImportError:
            return None
        try:
            decision = incrementAndCheck(
                userId = state.userId,
                deltaUsd = max(0.0, projectedStepCost),
                maxPerHour = self.maxCostUsdPerHour,
                maxPerDay = self.maxCostUsdPerDay,
            )
        except Exception:  # noqa: BLE001 - ledger failures must not kill the run
            logger.debug("cost ledger unavailable", exc_info = True)
            return None
        if decision.exceeded:
            return decision.reason or "per_hour"
        return None

    def _checkHeartbeat(self) -> str | None:
        if self.heartbeat is None:
            return None
        try:
            decision = self.heartbeat.check()
        except Exception:  # noqa: BLE001
            return None
        if decision.action == "terminate":
            return decision.reason or "heartbeat"
        return None

    async def _handlePlanDrift(
        self,
        *,
        state: AgentState,
        stepIndex: int,
        fragment: Any,
        currentUrl: str,
    ) -> str:
        """Phase 17: compare the current page to the fragment's expected
        state. On divergence, write a fresh :PreviewApproval node and
        block until the user approves or cancels.

        Returns:
            "proceed"          -> continue with the fragment as planned
            "abandon_fragment" -> skip fragment; drop into the model loop
            "cancelled"        -> user cancelled; state already marked

        The runner keeps its pre-phase behavior when self.previewHook
        is None or when the fragment carries no expected state hints.
        """
        expectedUrl = getattr(fragment, "expected_url", "") or ""
        if not expectedUrl or not currentUrl:
            return "proceed"
        if _urlsMatchLoose(expectedUrl, currentUrl):
            return "proceed"
        if self.previewHook is None:
            return "abandon_fragment"
        revisedSummary = (
            f"Plan drift at step {stepIndex}: the saved procedure expected "
            f"{expectedUrl!r} but the page is at {currentUrl!r}. The agent "
            f"will skip the replay fragment and ask the model for a fresh "
            f"action unless you cancel."
        )
        try:
            outcome = await _maybe(self.previewHook(state, revisedSummary))
        except Exception:  # noqa: BLE001 - preview failures must not block the run
            return "abandon_fragment"
        if outcome is None:
            return "abandon_fragment"
        status = getattr(outcome, "status", "approved")
        if status == "cancelled":
            state.markComplete("plan_drift_cancelled")
            return "cancelled"
        return "abandon_fragment"

    async def _redactForSink(self, screenshot: bytes) -> bytes:
        """Pipe a screenshot through the redactor, awaiting async probes.

        Accepts both sync callables (a lambda returning a list of
        `RedactionRegion`) and async probes (the Playwright DOM probe
        wired by default in `runner_factory`). If the redactor raises
        or returns nothing, the screenshot passes through unchanged.
        """
        if self.redactor is None or not screenshot:
            return screenshot
        try:
            result = self.redactor(self.browser, screenshot)
            if asyncio.iscoroutine(result):
                regions = await result
            else:
                regions = result
        except Exception:  # noqa: BLE001
            logger.debug("redactor raised", exc_info = True)
            return screenshot
        if not regions:
            return screenshot
        try:
            from apps.audit.redactor import redactScreenshot
        except ImportError:
            return screenshot
        return redactScreenshot(screenshot, regions)


def _failed(detail: str) -> StepResult:
    """Produce a `StepResult` that signals a terminal run-end reason.

    Used when the runner decides to stop before `BrowserController.execute`
    is called (captcha, injection, cost cap, heartbeat, approval reject).
    Staying on `StepResult` means the tuple return type at callers lines
    up with the type `BrowserController.execute` itself returns.
    """
    return StepResult(success = False, detail = detail)


def _urlsMatchLoose(expected: str, actual: str) -> bool:
    """Loose URL comparison for plan-drift detection.

    Treats URLs as matching if the scheme and host agree and the path
    prefix matches. Query strings and fragments are ignored because
    they rarely carry structural meaning for a replay.
    """
    try:
        from urllib.parse import urlparse
        a = urlparse(expected)
        b = urlparse(actual)
        if a.netloc and b.netloc and a.netloc != b.netloc:
            return False
        # Consider paths equivalent if one is a prefix of the other.
        pathA = a.path.rstrip("/") or "/"
        pathB = b.path.rstrip("/") or "/"
        return pathA == pathB or pathA.startswith(pathB) or pathB.startswith(pathA)
    except Exception:  # noqa: BLE001
        return expected == actual


def _looksLikeAuthRedirect(initialUrl: str, currentUrl: str) -> bool:
    if not initialUrl or not currentUrl:
        return False
    if any(hint in currentUrl for hint in AUTH_REDIRECT_HINTS):
        # Only flag if the user wasn't trying to land on a sign-in page.
        return not any(hint in initialUrl for hint in AUTH_REDIRECT_HINTS)
    return False


async def _maybe(value: Any) -> Any:
    """Await coroutines; pass non-coroutines through. Lets memory/replay
    accept both sync and async implementations interchangeably."""
    if asyncio.iscoroutine(value):
        return await value
    return value


def buildComputerUseRunner(
    *,
    browser: BrowserControllerProtocol,
    client: CuClient | None = None,
    onProgress: ProgressCb | None = None,
    auditSink: AuditCb | None = None,
    screenshotSink: ScreenshotSink | None = None,
    memory: Any | None = None,
    replayPlanner: Any | None = None,
    initialUrl: str = "",
    maxSteps: int = 20,
    approvalGate: ApprovalGate | None = None,
    modelId: str | None = None,
    maxRetriesPerStep: int = 1,
) -> ComputerUseRunner:
    resolvedClient: CuClient = client or GeminiComputerUseClient(
        modelId = modelId or GeminiComputerUseClient.modelId,
    )
    return ComputerUseRunner(
        browser = browser,
        client = resolvedClient,
        approvalGate = approvalGate or ApprovalGate(),
        onProgress = onProgress,
        auditSink = auditSink,
        screenshotSink = screenshotSink,
        memory = memory,
        replayPlanner = replayPlanner,
        initialUrl = initialUrl,
        maxSteps = maxSteps,
        maxRetriesPerStep = maxRetriesPerStep,
    )
