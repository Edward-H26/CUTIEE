"""Regression tests for the two-tier post-pivot cost model.

After the all-CU pivot, the tier system collapsed to:
    - tier 0  → zero cost (memory replay or harness-emitted navigation)
    - tier 1  → Computer Use model call

Anything else (legacy tier 2/3/4 from the deleted DOM router stack)
should never appear on a freshly-recorded step. These tests guard
against accidental regressions where someone re-introduces the old
tier numbering or makes replay charge a non-zero tier.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent.harness.computer_use_loop import ComputerUseRunner
from agent.harness.state import Action, ActionType
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
        return b"fake-png-bytes"

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
async def test_cu_step_records_tier_one() -> None:
    """Every model-driven step must record tier=1."""
    client = MockComputerUseClient(
        actionsToReturn = [
            Action(type = ActionType.CLICK_AT, coordinate = (10, 10)),
            Action(type = ActionType.FINISH, reasoning = "done"),
        ],
    )
    runner = ComputerUseRunner(
        browser = _SilentBrowser(),
        client = client,
        approvalGate = ApprovalGate(),
        initialUrl = "https://example.com",
    )
    state = await runner.run(userId = "u", taskId = "t", taskDescription = "demo")

    # Initial nav step is tier 0 (harness-emitted, no model call).
    assert state.history[0].action.tier == 0
    assert state.history[0].action.model_used == "harness"

    # Subsequent steps are tier 1 (CU model call) — never tier 4 / 2 / 3.
    cuSteps = state.history[1:]
    assert len(cuSteps) >= 1
    for step in cuSteps:
        assert step.action.tier == 1, (
            f"step {step.index} action {step.action.type} got tier "
            f"{step.action.tier}; CU steps must be tier 1"
        )


def test_replay_action_is_tier_zero() -> None:
    """Procedural replay must always be tier 0 (no model call → no cost)."""
    from agent.memory.bullet import Bullet
    from agent.memory.replay import _actionFromBullet

    bullet = Bullet(
        content = "step_index=0 action=click_at target='' value='' coordinate=(100,200)",
        memory_type = "procedural",
        topic = "task:demo",
        concept = "click_at",
        tags = ["task:demo", "domain:example.com"],
    )
    action = _actionFromBullet(bullet)
    assert action is not None
    assert action.tier == 0, "replay actions must never charge a non-zero tier"
    assert action.model_used == "replay"
    assert action.cost_usd == 0.0


def test_replay_with_legacy_cu_tag_still_tier_zero() -> None:
    """Bullets recorded before the pivot may carry the legacy 'tier:cu' tag.
    Replay should still produce tier=0 — the old tag was a now-stale hint."""
    from agent.memory.bullet import Bullet
    from agent.memory.replay import _actionFromBullet

    bullet = Bullet(
        content = "step_index=0 action=click_at target='' value='' coordinate=(50,60)",
        memory_type = "procedural",
        topic = "task:demo",
        concept = "click_at",
        tags = ["task:demo", "tier:cu"],  # legacy tag from pre-pivot bullets
    )
    action = _actionFromBullet(bullet)
    assert action is not None
    assert action.tier == 0
    assert action.cost_usd == 0.0


def test_no_tier_higher_than_one_is_emitted() -> None:
    """A whole-run scan: no live-recorded step should ever land at tier 2/3/4."""
    asyncio.set_event_loop_policy(None)
    client = MockComputerUseClient(
        actionsToReturn = [
            Action(type = ActionType.CLICK_AT, coordinate = (1, 2)),
            Action(type = ActionType.TYPE_AT, coordinate = (3, 4), value = "hello"),
            Action(type = ActionType.SCROLL_AT, coordinate = (5, 6), scrollDy = 100),
            Action(type = ActionType.FINISH, reasoning = "done"),
        ],
    )
    runner = ComputerUseRunner(
        browser = _SilentBrowser(),
        client = client,
        approvalGate = ApprovalGate(),
        initialUrl = "https://example.com",
    )
    state = asyncio.run(runner.run(userId = "u", taskId = "t", taskDescription = "demo"))

    for step in state.history:
        assert step.action.tier in {0, 1}, (
            f"step {step.index} got tier {step.action.tier}; "
            "only tier 0 (replay/harness) and tier 1 (CU) are valid post-pivot"
        )
