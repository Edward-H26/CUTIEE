"""Top-level agent loop.

The orchestrator is intentionally small. It owns the observation/action cycle,
the safety gate, and the audit hook. Memory, pruning, and routing are
injected so the same loop can run under three configurations:

* Phase-1 smoke test: mock VLM, no memory, no pruning, no router.
* Phase-2/3 integration: real memory and pruner, single client.
* Phase-4 production: full router, memory, pruner, safety gate, replay path.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent.browser.controller import BrowserController, StubBrowserController
from agent.harness.state import Action, ActionType, AgentState, ObservationStep
from agent.routing.models.base import PredictionResult, VLMClient
from agent.safety.approval_gate import ApprovalGate
from agent.safety.audit import AuditPayload, buildAuditPayload
from agent.safety.risk_classifier import classifyRisk

ProgressCallback = Callable[[AgentState, ObservationStep], Awaitable[None] | None]
AuditSink = Callable[[AuditPayload], Awaitable[None] | None]


@dataclass
class OrchestratorDeps:
    browser: Any
    vlmClient: VLMClient | None = None
    router: Any | None = None
    memory: Any | None = None
    pruner: Any | None = None
    replayPlanner: Any | None = None
    approvalGate: ApprovalGate = field(default_factory = ApprovalGate)
    onProgress: ProgressCallback | None = None
    auditSink: AuditSink | None = None


@dataclass
class Orchestrator:
    deps: OrchestratorDeps
    maxSteps: int = 25
    initialUrl: str = ""

    async def runTask(
        self,
        *,
        userId: str,
        taskId: str | None = None,
        taskDescription: str,
    ) -> AgentState:
        state = AgentState(
            taskId = taskId or str(uuid.uuid4()),
            userId = userId,
            taskDescription = taskDescription,
        )

        await self.deps.browser.start()
        try:
            if self.initialUrl:
                await self.deps.browser.execute(
                    Action(type = ActionType.NAVIGATE, target = self.initialUrl)
                )

            replayPlanner = self.deps.replayPlanner
            if replayPlanner is not None:
                replayPlan = await _maybe(replayPlanner.findReplayPlan(taskDescription, userId))
                if replayPlan is not None:
                    await self._executeReplay(state, replayPlan)
                    state.replayed = True

            if not state.isComplete:
                await self._runVlmLoop(state)

        finally:
            await self.deps.browser.stop()

        if not state.isComplete:
            state.markComplete("max_steps_reached")

        if self.deps.memory is not None and not state.replayed:
            await _maybe(self.deps.memory.processExecution(state))

        return state

    async def _runVlmLoop(self, state: AgentState) -> None:
        for stepIndex in range(state.stepCount(), self.maxSteps):
            dom = await self.deps.browser.observe()
            prunedContext = self._buildPrunedContext(state)
            priorBullets = await self._retrieveBullets(state)

            prediction = await self._invokeModel(
                taskDescription = state.taskDescription,
                dom = dom,
                prunedContext = prunedContext,
                priorBullets = priorBullets,
            )

            action = prediction.action
            action.cost_usd = prediction.costUsd
            action.confidence = prediction.confidence
            action.risk = classifyRisk(action, state.taskDescription)
            action.requires_approval = action.risk.value in {"high"}

            approvalStatus = "auto"
            if action.requires_approval:
                approved = await self.deps.approvalGate.requestApproval(action)
                approvalStatus = "approved" if approved else "rejected"
                if not approved:
                    state.markComplete("rejected_by_user")
                    break

            stepResult = await self.deps.browser.execute(action)
            step = ObservationStep(
                index = stepIndex,
                url = dom.url,
                domMarkdown = dom.markdown,
                domHash = dom.domHash,
                action = action,
                verificationOk = stepResult.success,
                verificationNote = stepResult.detail,
                durationMs = stepResult.durationMs,
            )
            state.appendStep(step)

            await self._emitProgress(state, step)
            await self._writeAudit(state, step, approvalStatus)

            if action.type == ActionType.FINISH:
                state.markComplete(action.reasoning or "finish_action")
                break
            if not stepResult.success:
                state.markComplete(f"action_failed:{stepResult.detail}")
                break

    async def _executeReplay(self, state: AgentState, plan: Any) -> None:
        for stepIndex, action in enumerate(getattr(plan, "actions", [])):
            action.cost_usd = 0.0
            action.tier = 0
            action.model_used = "replay"
            action.risk = classifyRisk(action, state.taskDescription)

            approvalStatus = "auto"
            if action.requires_approval or action.risk.value == "high":
                approved = await self.deps.approvalGate.requestApproval(action)
                approvalStatus = "approved" if approved else "rejected"
                if not approved:
                    state.markComplete("rejected_by_user_replay")
                    return

            result = await self.deps.browser.execute(action)
            step = ObservationStep(
                index = stepIndex,
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

    async def _invokeModel(
        self,
        *,
        taskDescription: str,
        dom: Any,
        prunedContext: str,
        priorBullets: str,
    ) -> PredictionResult:
        composedContext = (priorBullets + "\n\n" + prunedContext).strip()
        if self.deps.router is not None:
            decision = await _maybe(
                self.deps.router.routeAndPredict(
                    task = taskDescription,
                    dom = dom,
                    prunedContext = composedContext,
                )
            )
            return decision.prediction
        if self.deps.vlmClient is None:
            raise RuntimeError("Orchestrator requires either a router or a vlmClient.")
        return await self.deps.vlmClient.predictAction(taskDescription, dom, composedContext)

    def _buildPrunedContext(self, state: AgentState) -> str:
        if self.deps.pruner is None:
            return ""
        pruned = self.deps.pruner.prune(state.history)
        return self.deps.pruner.formatForPrompt(pruned)

    async def _retrieveBullets(self, state: AgentState) -> str:
        if self.deps.memory is None:
            return ""
        bullets = await _maybe(
            self.deps.memory.retrieveRelevantBullets(state.taskDescription, k = 6)
        )
        if not bullets:
            return ""
        return self.deps.memory.asPromptBlock(bullets)

    async def _emitProgress(self, state: AgentState, step: ObservationStep) -> None:
        if self.deps.onProgress is None:
            return
        result = self.deps.onProgress(state, step)
        if asyncio.iscoroutine(result):
            await result

    async def _writeAudit(
        self,
        state: AgentState,
        step: ObservationStep,
        approvalStatus: str,
    ) -> None:
        if self.deps.auditSink is None:
            return
        payload = buildAuditPayload(
            userId = state.userId,
            taskId = state.taskId,
            executionId = state.executionId,
            step = step,
            approvalStatus = approvalStatus,
        )
        result = self.deps.auditSink(payload)
        if asyncio.iscoroutine(result):
            await result


async def _maybe(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


def buildPhase1Orchestrator(
    *,
    vlmClient: VLMClient,
    initialUrl: str = "",
    maxSteps: int = 10,
) -> Orchestrator:
    """Factory for the Phase 1 smoke loop: stub browser + mock VLM."""
    return Orchestrator(
        deps = OrchestratorDeps(
            browser = StubBrowserController(),
            vlmClient = vlmClient,
        ),
        initialUrl = initialUrl,
        maxSteps = maxSteps,
    )


def buildLiveOrchestrator(
    *,
    browser: BrowserController,
    router: Any,
    memory: Any | None = None,
    pruner: Any | None = None,
    approvalGate: ApprovalGate | None = None,
    onProgress: ProgressCallback | None = None,
    auditSink: AuditSink | None = None,
    initialUrl: str = "",
    maxSteps: int = 25,
) -> Orchestrator:
    return Orchestrator(
        deps = OrchestratorDeps(
            browser = browser,
            router = router,
            memory = memory,
            pruner = pruner,
            approvalGate = approvalGate or ApprovalGate(),
            onProgress = onProgress,
            auditSink = auditSink,
        ),
        initialUrl = initialUrl,
        maxSteps = maxSteps,
    )
