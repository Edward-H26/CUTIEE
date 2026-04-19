"""cutiee-cu — Computer Use runner for LLM agents.

A standalone Python package extracted from CUTIEE. Drives a screenshot
↔ function-call loop against any model that supports the Gemini
`ComputerUse(environment="ENVIRONMENT_BROWSER")` tool, with auto-retry,
high-risk approval gating, screenshot persistence hooks, and optional
self-evolving memory + procedural replay.

Quick start:

    import asyncio
    from cutiee_cu import (
        ComputerUseRunner, GeminiComputerUseClient, BrowserController, ApprovalGate,
    )

    runner = ComputerUseRunner(
        browser = BrowserController(),
        client = GeminiComputerUseClient(),
        approvalGate = ApprovalGate(),
        initialUrl = "https://en.wikipedia.org",
    )
    state = asyncio.run(runner.run(
        userId = "demo", taskId = "wiki", taskDescription = "Find Jupiter's moons",
    ))

Required: `GEMINI_API_KEY` (live `GeminiComputerUseClient`) or use
`MockComputerUseClient` for tests / offline demos.

Optional integration with cutiee-ace:

    from cutiee_ace import ACEMemory, ACEPipeline, ReplayPlanner, InMemoryBulletStore
    memory = ACEMemory(userId="demo", store=InMemoryBulletStore())
    pipeline = ACEPipeline(memory=memory)
    runner = ComputerUseRunner(
        browser=BrowserController(),
        client=GeminiComputerUseClient(),
        approvalGate=ApprovalGate(),
        memory=pipeline,
        replayPlanner=ReplayPlanner(pipeline=pipeline),
    )
"""
from .browser.controller import (
    BrowserController,
    StepResult,
    StubBrowserController,
    browserFromEnv,
)
from .client.gemini_cu import (
    ComputerUseStep,
    GeminiComputerUseClient,
    MockComputerUseClient,
)
from .env_utils import envBool, envFloat, envInt, envStr
from .state import (
    Action,
    ActionType,
    AgentState,
    ObservationStep,
    RiskLevel,
)
from .runner import ComputerUseRunner, buildComputerUseRunner
from .safety.approval_gate import ApprovalGate, ApprovalRequest
from .safety.audit import AuditPayload, buildAuditPayload
from .safety.risk_classifier import classifyRisk

__version__ = "0.1.0"

__all__ = [
    # harness primitives
    "Action", "ActionType", "AgentState", "ObservationStep", "RiskLevel",
    "envBool", "envFloat", "envInt", "envStr",
    # browser
    "BrowserController", "StubBrowserController", "StepResult", "browserFromEnv",
    # CU client
    "ComputerUseStep", "GeminiComputerUseClient", "MockComputerUseClient",
    # runner
    "ComputerUseRunner", "buildComputerUseRunner",
    # safety
    "ApprovalGate", "ApprovalRequest",
    "AuditPayload", "buildAuditPayload", "classifyRisk",
]
