"""Heuristic risk classifier.

The classifier is intentionally simple and explainable: high-risk keywords
appear in either the action target/value or the surrounding task description.
The ACE pipeline can later override this via a `risk:high` tag on a procedural
bullet.
"""
from __future__ import annotations

from ..state import Action, ActionType, RiskLevel

HIGH_RISK_KEYWORDS = (
    "delete",
    "purchase",
    "buy",
    "checkout",
    "submit payment",
    "wire transfer",
    "transfer money",
    "send money",
    "subscribe",
    "cancel subscription",
    "logout all",
    "remove account",
    "deactivate",
    "share publicly",
    "publish",
    "send email",
    "post tweet",
    "approve",
)

MEDIUM_RISK_KEYWORDS = (
    "edit",
    "update",
    "save",
    "rename",
    "share",
    "invite",
    "send",
    "schedule",
)


def classifyRisk(action: Action, taskDescription: str = "") -> RiskLevel:
    if action.type == ActionType.FINISH:
        return RiskLevel.SAFE

    haystacks = [
        (action.target or "").lower(),
        (action.value or "").lower(),
        (action.reasoning or "").lower(),
        (taskDescription or "").lower(),
    ]

    for keyword in HIGH_RISK_KEYWORDS:
        for haystack in haystacks:
            if keyword in haystack:
                return RiskLevel.HIGH

    if action.type in (ActionType.CLICK, ActionType.SELECT, ActionType.PRESS):
        for keyword in MEDIUM_RISK_KEYWORDS:
            for haystack in haystacks:
                if keyword in haystack:
                    return RiskLevel.MEDIUM

    if action.type == ActionType.FILL and any("password" in h or "ssn" in h for h in haystacks):
        return RiskLevel.HIGH

    if action.type == ActionType.NAVIGATE:
        return RiskLevel.LOW

    return RiskLevel.LOW
