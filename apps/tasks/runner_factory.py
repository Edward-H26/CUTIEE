"""Factory functions that compose the Computer Use runner.

Splits wiring out of `services.py` so the run-task entry point stays
focused on persistence + progress publishing. Tests can import this
factory directly to swap any single collaborator (browser, memory,
replay planner, screenshot sink) without touching the rest.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from agent.browser.controller import StubBrowserController, browserFromEnv
from agent.harness.computer_use_loop import ComputerUseRunner, buildComputerUseRunner
from agent.harness.state import Action, ActionType, AgentState, ObservationStep
from agent.memory.ace_memory import ACEMemory
from agent.memory.pipeline import ACEPipeline
from agent.memory.replay import ReplayPlanner
from agent.routing.models.gemini_cu import MockComputerUseClient
from agent.safety.approval_gate import ApprovalGate
from apps.audit.repo import appendAudit
from apps.memory_app.store import Neo4jBulletStore
from apps.tasks.approval_queue import buildExecutionGate

ProgressCb = Callable[[AgentState, ObservationStep], Awaitable[None] | None]
ScreenshotCb = Callable[[str, int, bytes], Awaitable[None] | None]


def buildMockCuRunner(*, initialUrl: str = "", maxSteps: int = 6) -> ComputerUseRunner:
    """Demo / unconfigured-env runner. Uses MockComputerUseClient so no
    GEMINI_API_KEY is required and no browser binary is launched (stub).

    The scripted action list intentionally starts AFTER the initial NAVIGATE
    that the runner emits itself — first scripted action is the click.
    """
    mockClient = MockComputerUseClient(
        label = "mock-cu-demo",
        actionsToReturn = [
            Action(type = ActionType.CLICK_AT, coordinate = (640, 320), reasoning = "demo click"),
            Action(type = ActionType.FINISH, reasoning = "demo complete"),
        ],
        fixedCostUsd = 0.0,
    )
    return ComputerUseRunner(
        browser = StubBrowserController(),
        client = mockClient,
        approvalGate = ApprovalGate(),
        initialUrl = initialUrl,
        maxSteps = maxSteps,
    )


def buildLiveCuRunnerForUser(
    *,
    userId: str,
    initialUrl: str = "",
    executionId: str | None = None,
    onProgress: ProgressCb | None = None,
    screenshotSink: ScreenshotCb | None = None,
    useStubBrowser: bool = False,
    maxSteps: int = 25,
) -> ComputerUseRunner:
    """Compose the production CU runner for a single user.

    `useStubBrowser=True` is the right default on Render's web tier (no
    chromium binary). Workers that ship Playwright should pass
    `useStubBrowser=False` so the agent can actually drive a browser.
    """
    memory = ACEMemory(userId = str(userId), store = Neo4jBulletStore())
    memory.loadFromStore()
    pipeline = ACEPipeline(memory = memory)
    replayPlanner = ReplayPlanner(pipeline = pipeline)

    domain = _domainFromUrl(initialUrl)
    browser = (
        StubBrowserController()
        if useStubBrowser
        else browserFromEnv(defaultHeadless = False, domain = domain)
    )

    decider = buildExecutionGate(executionId) if executionId else None

    return buildComputerUseRunner(
        browser = browser,
        onProgress = onProgress,
        auditSink = appendAudit,
        screenshotSink = screenshotSink,
        memory = pipeline,
        replayPlanner = replayPlanner,
        initialUrl = initialUrl,
        maxSteps = maxSteps,
        approvalGate = ApprovalGate(decider = decider),
    )


def _domainFromUrl(url: str) -> str:
    if not url or "://" not in url:
        return ""
    rest = url.split("://", 1)[1]
    return rest.split("/", 1)[0]
