"""Computer Use runner — the only agent loop in CUTIEE.

Drives a screenshot ↔ function-call loop against any model that supports
the Gemini ComputerUse tool (default: gemini-flash-latest). Owns:
  - replay: check for procedural-memory templates before invoking the model
  - the screenshot↔action loop with auto-retry
  - per-step audit + progress + screenshot persistence
  - memory writeback at end of run (Reflector → Gate → Curator → Apply)

The DOM-router stack (AdaptiveRouter / GeminiCloudClient / DOMState
extraction / RecencyPruner) was removed in favor of CU-everywhere; CU is
now cheap enough at flash pricing that maintaining two parallel paths
isn't worth the code weight.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..browser.controller import BrowserController
from .state import (
    Action,
    ActionType,
    AgentState,
    ObservationStep,
    RiskLevel,
)
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
    browser: BrowserController
    client: Any  # GeminiComputerUseClient | MockComputerUseClient (duck-typed)
    approvalGate: ApprovalGate
    onProgress: ProgressCb | None = None
    auditSink: AuditCb | None = None
    screenshotSink: ScreenshotSink | None = None
    memory: Any | None = None  # ACEPipeline; processExecution(state) called at end
    replayPlanner: Any | None = None  # ReplayPlanner; findReplayPlan(task, userId)
    initialUrl: str = ""
    maxSteps: int = 20
    maxRetriesPerStep: int = 1
    # Pre-matched ActionNodes from subgraph matcher (Phase 3 hybrid replay).
    # Set externally before run(); the runner replays them at zero cost
    # then continues with the model loop for any remaining steps.
    prematchedNodes: list = field(default_factory = list)

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
        await self.browser.start()
        try:
            # Replay path 1: whole-template procedural memory (pre-Phase-3)
            replayPlan = None
            if self.replayPlanner is not None:
                replayPlan = await _maybe(
                    self.replayPlanner.findReplayPlan(taskDescription, userId)
                )

            if replayPlan is not None:
                # Replay templates record the initial NAVIGATE; don't double-emit.
                await self._executeReplay(state, replayPlan)
                state.replayed = True
            else:
                # Replay path 2: Phase 3 hybrid replay — execute pre-matched
                # ActionNodes at zero cost, then drive CU for the remaining
                # steps. The state is NOT marked replayed because we still
                # invoke the model afterwards; the bandit gets to see real
                # rewards for the suffix.
                if self.prematchedNodes:
                    await self._executePrematchedNodes(state)
                elif self.initialUrl:
                    await self._recordInitialNavigation(state)
                if not state.isComplete:
                    await self._runLoop(state)
        finally:
            await self.browser.stop()

        if not state.isComplete:
            state.markComplete("max_steps_reached")

        # Self-evolving memory writeback. Skipped for replay runs because the
        # template that produced them already encodes the lesson.
        if self.memory is not None and not state.replayed:
            await _maybe(self.memory.processExecution(state))

        return state

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

    async def _runLoop(self, state: AgentState) -> None:
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
            step, stepResult, screenshot, currentUrl = await self._executeOneStepWithRetry(
                state = state,
                stepIndex = stepIndex,
                screenshot = screenshot,
                currentUrl = currentUrl,
            )

            if step is None:
                # Approval rejected; state already finalized.
                return

            if step.action and step.action.type == ActionType.FINISH:
                state.markComplete(step.action.reasoning or "finish_action")
                return

            if not stepResult.success:
                state.markComplete(f"action_failed:{stepResult.detail}")
                return

    async def _executeOneStepWithRetry(
        self,
        *,
        state: AgentState,
        stepIndex: int,
        screenshot: bytes,
        currentUrl: str,
    ) -> tuple[ObservationStep | None, "Result", bytes, str]:
        """Run one model→browser step. On failure, retry once with a fresh screenshot.

        Captures exactly ONE screenshot per attempt: the post-action shot
        is broadcast to both the persistence sink and the next iteration
        so we don't pay for two captures per step.
        """
        attempts = 0
        while True:
            cuStep = await self.client.nextAction(screenshot, currentUrl)
            action = cuStep.action
            # Tier 1 = the only model-call tier in CUTIEE. Tier 0 is reserved
            # for zero-cost steps (memory replay, harness-emitted navigation).
            # The "T0 vs T1" split is what the dashboard chart uses to show
            # how often memory saved a model call.
            action.tier = 1
            action.risk = classifyRisk(action, state.taskDescription)
            action.requires_approval = action.risk == RiskLevel.HIGH

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
            screenshot = await self.browser.captureScreenshot()
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


@dataclass
class Result:
    """Tiny stand-in for StepResult so the inner type annotation stays local."""
    success: bool
    detail: str = ""


def _failed(detail: str) -> Result:
    return Result(success = False, detail = detail)


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
    browser: BrowserController,
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
    client = GeminiComputerUseClient(modelId = modelId or GeminiComputerUseClient.modelId)
    return ComputerUseRunner(
        browser = browser,
        client = client,
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
