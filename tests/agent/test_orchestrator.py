"""Phase-1 orchestrator smoke tests."""
from __future__ import annotations

import asyncio

from agent.harness.orchestrator import buildPhase1Orchestrator
from agent.harness.state import Action, ActionType
from agent.routing.models.mock import MockVLMClient


def test_orchestratorRunsScriptedActionsToFinish():
    client = MockVLMClient(
        label = "smoke",
        actionsToReturn = [
            Action(type = ActionType.NAVIGATE, target = "http://example.com"),
            Action(type = ActionType.CLICK, target = "#submit"),
            Action(type = ActionType.FINISH, reasoning = "done"),
        ],
        fixedConfidence = 0.9,
    )
    orch = buildPhase1Orchestrator(vlmClient = client, maxSteps = 5)
    state = asyncio.run(orch.runTask(userId = "u1", taskDescription = "smoke"))
    assert state.isComplete
    assert state.completionReason == "done"
    assert state.stepCount() == 3


def test_orchestratorBoundsAtMaxSteps():
    client = MockVLMClient(
        label = "loop",
        actionsToReturn = [Action(type = ActionType.CLICK, target = "#x") for _ in range(10)],
        fixedConfidence = 0.9,
    )
    orch = buildPhase1Orchestrator(vlmClient = client, maxSteps = 3)
    state = asyncio.run(orch.runTask(userId = "u1", taskDescription = "loop"))
    assert state.stepCount() == 3
    assert state.completionReason in {"max_steps_reached", ""}
