"""Unit tests for the safety subsystem."""
from __future__ import annotations

import asyncio

from agent.harness.state import Action, ActionType, ObservationStep, RiskLevel
from agent.safety.approval_gate import ApprovalGate
from agent.safety.audit import buildAuditPayload
from agent.safety.risk_classifier import classifyRisk


def test_classifyRiskHighOnDelete():
    action = Action(type = ActionType.CLICK, target = "#delete-account", reasoning = "delete the account")
    assert classifyRisk(action, "remove account") == RiskLevel.HIGH


def test_classifyRiskHighOnPasswordFill():
    action = Action(type = ActionType.FILL, target = "input[type=password]", value = "secret-password")
    assert classifyRisk(action, "log into bank") == RiskLevel.HIGH


def test_classifyRiskLowOnNavigate():
    action = Action(type = ActionType.NAVIGATE, target = "http://example.com")
    assert classifyRisk(action, "browse") == RiskLevel.LOW


def test_classifyRiskSafeOnFinish():
    assert classifyRisk(Action(type = ActionType.FINISH), "anything") == RiskLevel.SAFE


def test_approvalGateAutoApprovesBelowThreshold():
    gate = ApprovalGate(autoApproveBelow = RiskLevel.MEDIUM)
    action = Action(type = ActionType.NAVIGATE, target = "http://x", risk = RiskLevel.LOW)
    assert asyncio.run(gate.requestApproval(action)) is True


def test_approvalGateInvokesDeciderOnHighRisk():
    decisions: list[bool] = []

    async def decider(req):
        decisions.append(True)
        return False

    gate = ApprovalGate(decider = decider)
    action = Action(type = ActionType.CLICK, target = "#delete", risk = RiskLevel.HIGH)
    result = asyncio.run(gate.requestApproval(action))
    assert decisions == [True]
    assert result is False


def test_buildAuditPayloadFromStep():
    step = ObservationStep(
        index = 2,
        url = "http://x",
        action = Action(
            type = ActionType.CLICK,
            target = "#submit",
            tier = 2,
            cost_usd = 0.0005,
            risk = RiskLevel.LOW,
            model_used = "mock",
            reasoning = "click",
        ),
        verificationOk = True,
    )
    payload = buildAuditPayload(
        userId = "u1",
        taskId = "t1",
        executionId = "e1",
        step = step,
    )
    d = payload.asDict()
    assert d["user_id"] == "u1"
    assert d["action"] == "click"
    assert d["target"] == "#submit"
    assert d["tier"] == 2
    assert abs(d["cost_usd"] - 0.0005) < 1e-9
