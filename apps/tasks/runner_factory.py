"""Factory functions that compose the Computer Use runner.

Splits wiring out of `services.py` so the run-task entry point stays
focused on persistence + progress publishing. Tests can import this
factory directly to swap any single collaborator (browser, memory,
replay planner, screenshot sink) without touching the rest.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agent.browser.controller import StubBrowserController, browserFromEnv
from agent.harness.computer_use_loop import ComputerUseRunner, buildComputerUseRunner
from agent.harness.config import Config
from agent.harness.state import Action, ActionType, AgentState, ObservationStep
from agent.memory.ace_memory import ACEMemory
from agent.memory.pipeline import ACEPipeline
from agent.memory.replay import ReplayPlanner
from agent.routing.cu_client import CuClient
from agent.routing.models.gemini_cu import GeminiComputerUseClient, MockComputerUseClient
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
        else browserFromEnv(defaultHeadless = False, domain = domain, userId = str(userId))
    )

    decider = buildExecutionGate(executionId) if executionId else None
    client = _buildCuClientFromEnv(cdpUrl = _cdpUrlFromBrowser(browser), maxSteps = maxSteps)

    runner = buildComputerUseRunner(
        browser = browser,
        client = client,
        onProgress = onProgress,
        auditSink = appendAudit,
        screenshotSink = screenshotSink,
        memory = pipeline,
        replayPlanner = replayPlanner,
        initialUrl = initialUrl,
        maxSteps = maxSteps,
        approvalGate = ApprovalGate(decider = decider),
    )
    # Phase 8 concrete DOM probe: when a real Playwright page is
    # available, scan for password / cc-number / cc-csc inputs and
    # redact their bounding boxes before screenshots enter the sink.
    # The stub browser has no `.page`, so the probe returns an empty
    # region list and redaction is a no-op by default.
    from apps.audit.redactor import playwrightDomRedactor
    runner.redactor = playwrightDomRedactor
    return runner


def _buildCuClientFromEnv(*, cdpUrl: str | None, maxSteps: int) -> CuClient:
    """Dispatch between GeminiComputerUseClient and BrowserUseClient.

    `Config.fromEnv()` already validated `CUTIEE_CU_BACKEND` and the
    required credential; we just map the selected backend to a concrete
    client. Both backends share `GEMINI_API_KEY` because browser-use is
    wired to Gemini 3 Flash in this plan.

    A `CuClient` Protocol check runs before returning so that a future
    adapter missing `primeTask` or `nextAction` fails at runner
    construction instead of at the first model call inside the loop.
    """
    config = Config.fromEnv()
    client: CuClient
    if config.cuBackend == "browser_use":
        from agent.routing.models.browser_use_client import BrowserUseClient
        client = BrowserUseClient(cdpUrl = cdpUrl, maxSteps = maxSteps)
    else:
        client = GeminiComputerUseClient()
    if not isinstance(client, CuClient):
        raise RuntimeError(
            f"CUTIEE_CU_BACKEND={config.cuBackend!r} produced a client "
            f"({type(client).__name__}) that does not satisfy the CuClient "
            "Protocol. Check that `name`, `primeTask`, and async `nextAction` "
            "are all declared with the expected signatures in the adapter."
        )
    return client


def _cdpUrlFromBrowser(browser: Any) -> str | None:
    """Surface the controller's CDP URL for CU backends that attach over CDP."""
    return getattr(browser, "cdpUrl", None)


def _domainFromUrl(url: str) -> str:
    if not url or "://" not in url:
        return ""
    rest = url.split("://", 1)[1]
    return rest.split("/", 1)[0]
