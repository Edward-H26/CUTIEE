"""End-to-end test for the Phase 3 hybrid-replay path.

Verifies that when the runner is given pre-matched ActionNodes, it
executes them at zero cost (tier=0, model_used="replay-graph") and
THEN drives the model loop for the unmatched suffix. This is the
distinctive behavior that differentiates partial replay from
whole-template replay.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent.harness.computer_use_loop import ComputerUseRunner
from agent.harness.state import Action, ActionType
from agent.memory.action_graph import ActionNode
from agent.routing.models.gemini_cu import ComputerUseStep, MockComputerUseClient
from agent.safety.approval_gate import ApprovalGate


@dataclass
class _SilentBrowser:
    fakeUrl: str = "https://example.com/app"
    actions: list[Action] = field(default_factory = list)
    started: bool = False
    stopped: bool = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def captureScreenshot(self) -> bytes:
        return b"fake-png"

    async def currentUrl(self) -> str:
        return self.fakeUrl

    async def execute(self, action: Action) -> Any:
        self.actions.append(action)

        @dataclass
        class _R:
            success: bool = True
            detail: str = ""
            durationMs: int = 1
        return _R()


@pytest.mark.asyncio
async def test_runner_executes_prematched_nodes_at_tier_zero() -> None:
    """Pre-matched nodes should land in state.history with tier=0."""
    prematched = [
        ActionNode(action_type = "navigate", target = "https://docs.google.com",
                   description = "open sheet"),
        ActionNode(action_type = "click_at", coord_x = 100, coord_y = 200,
                   description = "locate column C"),
    ]
    runner = ComputerUseRunner(
        browser = _SilentBrowser(),
        client = MockComputerUseClient(actionsToReturn = [
            Action(type = ActionType.TYPE_AT, coordinate = (100, 220), value = "=SUM(A:B)"),
            Action(type = ActionType.FINISH, reasoning = "done"),
        ]),
        approvalGate = ApprovalGate(),
        prematchedNodes = prematched,
    )

    state = await runner.run(userId = "u", taskId = "t", taskDescription = "sum cols")

    # Step 0 + 1: pre-matched (tier 0, model="replay-graph")
    assert state.history[0].action.tier == 0
    assert state.history[0].action.model_used == "replay-graph"
    assert state.history[1].action.tier == 0
    assert state.history[1].action.model_used == "replay-graph"
    # Step 2+: model-driven (tier 1, model="mock-cu")
    assert state.history[2].action.tier == 1
    assert state.history[2].action.model_used == "mock-cu"
    assert state.isComplete


@pytest.mark.asyncio
async def test_runner_with_no_prematched_falls_through_to_initial_nav() -> None:
    """When prematchedNodes is empty AND initialUrl is set, normal startup."""
    runner = ComputerUseRunner(
        browser = _SilentBrowser(),
        client = MockComputerUseClient(actionsToReturn = [
            Action(type = ActionType.FINISH, reasoning = "done"),
        ]),
        approvalGate = ApprovalGate(),
        initialUrl = "https://example.com",
        prematchedNodes = [],
    )
    state = await runner.run(userId = "u", taskId = "t", taskDescription = "demo")
    # Initial nav step (tier 0, harness) + FINISH from mock (tier 1, mock-cu)
    assert state.history[0].action.type == ActionType.NAVIGATE
    assert state.history[0].action.model_used == "harness"
    assert state.isComplete


@pytest.mark.asyncio
async def test_prematched_node_failure_falls_through_to_model() -> None:
    """If a pre-matched action fails, runner stops replay and lets model drive."""

    @dataclass
    class _FlakyBrowser(_SilentBrowser):
        failOnGraphReplay: bool = True

        async def execute(self, action: Action) -> Any:
            self.actions.append(action)

            @dataclass
            class _R:
                success: bool
                detail: str = ""
                durationMs: int = 1
            # Fail the FIRST graph-replay action; subsequent (model-driven) succeed.
            if self.failOnGraphReplay and action.model_used == "replay-graph":
                self.failOnGraphReplay = False
                return _R(success = False, detail = "stale-coord")
            return _R(success = True)

    prematched = [
        ActionNode(action_type = "click_at", coord_x = 100, coord_y = 200, description = "stale"),
    ]
    runner = ComputerUseRunner(
        browser = _FlakyBrowser(),
        client = MockComputerUseClient(actionsToReturn = [
            Action(type = ActionType.CLICK_AT, coordinate = (105, 205)),
            Action(type = ActionType.FINISH, reasoning = "done"),
        ]),
        approvalGate = ApprovalGate(),
        prematchedNodes = prematched,
    )
    state = await runner.run(userId = "u", taskId = "t", taskDescription = "demo")
    # The failed graph-replay step is recorded with tier=0 and verificationOk=False
    assert state.history[0].action.tier == 0
    assert state.history[0].verificationOk is False
    # Model continues from there
    assert state.isComplete
