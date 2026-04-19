"""Bridge between Django views and the agent harness.

`runTaskForUser` is the function the API endpoint calls. It composes the
right orchestrator (router + memory + pruner + safety gate) for the active
`CUTIEE_ENV`, runs the task synchronously inside a thread, and persists the
resulting state back to Neo4j. Thread execution keeps Django's WSGI stack
unaware of the agent's asyncio event loop.

The function returns a small `TaskRunSummary` so callers can render the
HTMX progress block without re-querying Neo4j.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from agent.browser.controller import BrowserController, StubBrowserController
from agent.harness.orchestrator import (
    Orchestrator,
    buildLiveOrchestrator,
    buildPhase1Orchestrator,
)
from agent.harness.state import Action, ActionType, AgentState
from agent.memory.ace_memory import ACEMemory
from agent.memory.pipeline import ACEPipeline
from agent.memory.replay import ReplayPlanner
from agent.pruning.context_window import RecencyPruner
from agent.routing.factory import buildMockRouter, buildRouter
from agent.routing.models.mock import MockVLMClient
from agent.safety.approval_gate import ApprovalGate
from apps.audit.repo import appendAudit
from apps.memory_app.repo import upsertTemplate
from apps.tasks import progress_backend, repo as tasksRepo


@dataclass
class TaskRunSummary:
    taskId: str
    executionId: str
    stepCount: int
    totalCostUsd: float
    completed: bool
    completionReason: str
    replayed: bool
    tierUsage: dict[int, int]


def runTaskForUser(
    *,
    userId: str,
    taskId: str,
    description: str,
    initialUrl: str = "",
    useMockAgent: bool | None = None,
) -> TaskRunSummary:
    state = asyncio.run(
        _runTaskAsync(
            userId = userId,
            taskId = taskId,
            description = description,
            initialUrl = initialUrl,
            useMockAgent = useMockAgent,
        )
    )
    tasksRepo.persistAgentState(userId = userId, taskId = taskId, state = state)
    if state.replayed and state.templateId is None and state.history:
        templateId = upsertTemplate(
            userId = userId,
            description = description,
            domain = _domainFromUrl(initialUrl),
            embedding = None,
            actions = [step.action.asDict() if step.action else {} for step in state.history],
        )
        state.templateId = templateId

    summary = _summarize(state)
    _publishProgress(state.executionId, summary, finished = True)
    return summary


async def _runTaskAsync(
    *,
    userId: str,
    taskId: str,
    description: str,
    initialUrl: str,
    useMockAgent: bool | None,
) -> AgentState:
    cutieeEnv = os.environ.get("CUTIEE_ENV", "")
    forceMock = useMockAgent if useMockAgent is not None else cutieeEnv not in {"local", "production"}

    if forceMock:
        orchestrator = _buildMockOrchestrator(initialUrl = initialUrl)
    else:
        orchestrator = _buildLiveOrchestratorForUser(userId = userId, initialUrl = initialUrl)

    return await orchestrator.runTask(
        userId = str(userId),
        taskId = taskId,
        taskDescription = description,
    )


def _buildMockOrchestrator(*, initialUrl: str) -> Orchestrator:
    mockClient = MockVLMClient(
        label = "mock-demo",
        actionsToReturn = [
            Action(type = ActionType.NAVIGATE, target = initialUrl or "about:blank", reasoning = "open initial url"),
            Action(type = ActionType.CLICK, target = "button[type='submit']", reasoning = "click primary"),
            Action(type = ActionType.FINISH, reasoning = "demo complete"),
        ],
        fixedConfidence = 0.9,
        fixedCostUsd = 0.0,
    )
    return buildPhase1Orchestrator(vlmClient = mockClient, initialUrl = initialUrl, maxSteps = 6)


def _buildLiveOrchestratorForUser(*, userId: str, initialUrl: str) -> Orchestrator:
    memory = ACEMemory(userId = str(userId))
    memory.loadFromStore()
    pipeline = ACEPipeline(memory = memory)
    replayPlanner = ReplayPlanner(pipeline = pipeline)
    pruner = RecencyPruner()

    try:
        router = buildRouter()
    except RuntimeError:
        router = buildMockRouter()

    browser: Any
    try:
        browser = BrowserController(headless = True)
    except Exception:
        browser = StubBrowserController()

    orchestrator = buildLiveOrchestrator(
        browser = browser,
        router = router,
        memory = pipeline,
        pruner = pruner,
        approvalGate = ApprovalGate(),
        onProgress = _makeProgressCallback(),
        auditSink = lambda payload: appendAudit(payload),
        initialUrl = initialUrl,
    )
    orchestrator.deps.replayPlanner = replayPlanner
    return orchestrator


def _makeProgressCallback():
    def _cb(state, step):
        _publishProgress(state.executionId, _summarize(state, latestStep = step), finished = False)
    return _cb


def _publishProgress(executionId: str, summary: TaskRunSummary, *, finished: bool) -> None:
    payload = {
        "executionId": summary.executionId,
        "stepCount": summary.stepCount,
        "totalCostUsd": summary.totalCostUsd,
        "completed": finished and summary.completed,
        "completionReason": summary.completionReason,
        "replayed": summary.replayed,
        "tierUsage": summary.tierUsage,
        "finished": finished,
    }
    progress_backend.publishProgress(executionId, payload)


def fetchProgress(executionId: str) -> dict[str, Any] | None:
    return progress_backend.fetchProgress(executionId)


def _summarize(state: AgentState, *, latestStep = None) -> TaskRunSummary:
    tierUsage: dict[int, int] = {}
    for step in state.history:
        if step.action is None:
            continue
        tierUsage[step.action.tier] = tierUsage.get(step.action.tier, 0) + 1
    if latestStep is not None and latestStep.action is not None:
        tierUsage.setdefault(latestStep.action.tier, 0)

    return TaskRunSummary(
        taskId = state.taskId,
        executionId = state.executionId,
        stepCount = state.stepCount(),
        totalCostUsd = round(state.totalCostUsd, 6),
        completed = state.isComplete,
        completionReason = state.completionReason,
        replayed = state.replayed,
        tierUsage = tierUsage,
    )


def _domainFromUrl(url: str) -> str:
    if not url or "://" not in url:
        return ""
    rest = url.split("://", 1)[1]
    return rest.split("/", 1)[0]
