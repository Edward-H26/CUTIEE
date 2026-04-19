"""Bridge between Django views and the Computer Use agent runner.

`runTaskForUser` is the function the API endpoint calls. CUTIEE runs every
task through `ComputerUseRunner` (screenshot + pixel coordinates via
gemini-flash-latest by default). The DOM-router stack was removed once
Gemini Flash gained the ComputerUse tool at flash pricing.

Wiring lives in `runner_factory.py`; this module owns the run-and-persist
sequence plus the live-progress publish path. The agent runs in a
background thread so Django's WSGI stack stays unaware of the asyncio
event loop the runner spawns.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from agent.harness.state import AgentState, ObservationStep
from apps.audit.screenshot_store import Neo4jScreenshotStore
from apps.memory_app.repo import upsertTemplate
from apps.tasks import progress_backend, repo as tasksRepo
from apps.tasks.runner_factory import buildLiveCuRunnerForUser, buildMockCuRunner

_SCREENSHOT_STORE: Neo4jScreenshotStore | None = None
_SCREENSHOT_STORE_LOCK = threading.Lock()
_logger = logging.getLogger("cutiee")


def _screenshotStore() -> Neo4jScreenshotStore:
    """Thread-safe lazy singleton for the Neo4j screenshot store.

    The agent runs in a background thread; the Django request thread
    also touches this for the screenshot-serving view. Without the lock,
    two simultaneous first-touches would race and instantiate two
    stores (and two driver pools).
    """
    global _SCREENSHOT_STORE
    if _SCREENSHOT_STORE is not None:
        return _SCREENSHOT_STORE
    with _SCREENSHOT_STORE_LOCK:
        if _SCREENSHOT_STORE is None:
            _SCREENSHOT_STORE = Neo4jScreenshotStore()
    return _SCREENSHOT_STORE


def persistScreenshot(executionId: str, stepIndex: int, pngBytes: bytes) -> None:
    try:
        _screenshotStore().save(executionId, stepIndex, pngBytes)
    except Exception:  # noqa: BLE001 - persistence is best-effort, run continues
        _logger.warning(
            "Failed to persist CU screenshot for %s step %s", executionId, stepIndex,
            exc_info = True,
        )


# Browser policy:
#
# Render's web tier ships without `playwright install chromium`, so the
# default for the demo deploy is the stub browser. Real-browser deploys
# (worker dynos with Playwright installed, or local laptops with chromium)
# must opt in by setting CUTIEE_USE_STUB_BROWSER=0.
USE_STUB_BROWSER = os.environ.get("CUTIEE_USE_STUB_BROWSER", "true").lower() not in {"0", "false", "no"}


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
    useComputerUse: bool | None = None,  # accepted for back-compat; CU is the only mode
) -> TaskRunSummary:
    """Drive one task to completion through the Computer Use runner.

    `useComputerUse` is accepted for back-compatibility with the API
    layer but is now ignored — there is only one runner. `useMockAgent`
    forces the scripted MockComputerUseClient (used for tests / when
    CUTIEE_ENV is unset for demo mode).
    """
    del useComputerUse  # reserved; previously selected DOM vs CU
    state = asyncio.run(
        _runTaskAsync(
            userId = userId,
            taskId = taskId,
            description = description,
            initialUrl = initialUrl,
            useMockAgent = useMockAgent,
        )
    )

    # Template first, so the execution row can carry the templateId immediately.
    if state.replayed and state.templateId is None and state.history:
        state.templateId = upsertTemplate(
            userId = userId,
            description = description,
            domain = _domainFromUrl(initialUrl),
            embedding = None,
            actions = [step.action.asDict() if step.action else {} for step in state.history],
        )

    tasksRepo.persistAgentState(userId = userId, taskId = taskId, state = state)

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
    forceMock = useMockAgent if useMockAgent is not None else cutieeEnv != "production"

    executionId = str(uuid.uuid4())

    if forceMock:
        runner = buildMockCuRunner(initialUrl = initialUrl)
    else:
        runner = buildLiveCuRunnerForUser(
            userId = str(userId),
            initialUrl = initialUrl,
            executionId = executionId,
            onProgress = _progressCallback,
            screenshotSink = persistScreenshot,
            useStubBrowser = USE_STUB_BROWSER,
        )

    return await runner.run(
        userId = str(userId),
        taskId = taskId,
        taskDescription = description,
        executionId = executionId,
    )


def _progressCallback(state: AgentState, step: ObservationStep) -> None:
    _publishProgress(state.executionId, _summarize(state, latestStep = step), finished = False)


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


def _summarize(state: AgentState, *, latestStep: ObservationStep | None = None) -> TaskRunSummary:
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
