"""Unit tests for the agent state dataclasses."""
from __future__ import annotations

from agent.harness.state import (
    Action,
    ActionType,
    AgentState,
    ObservationStep,
    RiskLevel,
)


def test_actionDefaults():
    action = Action(type = ActionType.CLICK)
    assert action.target == ""
    assert action.tier == 0
    assert action.confidence == 0.0
    assert action.risk == RiskLevel.SAFE
    assert action.cost_usd == 0.0
    assert action.requires_approval is False


def test_actionAsDict():
    action = Action(
        type = ActionType.FILL,
        target = "#email",
        value = "alice@example.com",
        tier = 1,
        cost_usd = 0.0001,
    )
    d = action.asDict()
    assert d["type"] == "fill"
    assert d["target"] == "#email"
    assert d["value"] == "alice@example.com"
    assert d["tier"] == 1


def test_actionFinishDetect():
    assert Action(type = ActionType.FINISH).isFinish() is True
    assert Action(type = ActionType.CLICK).isFinish() is False


def test_observationStepShortSummary():
    step = ObservationStep(
        index = 3,
        action = Action(type = ActionType.NAVIGATE, target = "http://example.com"),
        verificationOk = True,
    )
    summary = step.shortSummary()
    assert "step=3" in summary
    assert "action=navigate" in summary
    assert "ok" in summary

    failed = ObservationStep(index = 4, action = Action(type = ActionType.CLICK), verificationOk = False)
    assert "fail" in failed.shortSummary()


def test_agentStateAccumulatesCost():
    state = AgentState(taskId = "t", userId = "u", taskDescription = "demo")
    state.appendStep(ObservationStep(index = 0, action = Action(type = ActionType.CLICK, cost_usd = 0.001)))
    state.appendStep(ObservationStep(index = 1, action = Action(type = ActionType.CLICK, cost_usd = 0.002)))
    assert abs(state.totalCostUsd - 0.003) < 1e-9
    assert state.stepCount() == 2
    assert len(state.lastNSteps(1)) == 1


def test_markComplete():
    state = AgentState(taskId = "t", userId = "u", taskDescription = "demo")
    state.markComplete("done")
    assert state.isComplete is True
    assert state.completionReason == "done"
    assert state.finishedAt is not None
