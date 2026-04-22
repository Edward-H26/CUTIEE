"""Heuristic risk classifier.

The classifier is intentionally simple and explainable: high-risk keywords
appear in either the action target/value or the surrounding task description.
The ACE pipeline can later override this via a `risk:high` tag on a procedural
bullet.

Keyword matching uses regex word boundaries so that "delete" does not match
"undelete", "deactivate" does not match "reactivate", and "publish" does not
match "unpublished". The password and SSN check for FILL actions keeps
substring matching because sensitive selectors routinely appear as
"input[name=password]" or "ssn-last-four".
"""
from __future__ import annotations

import re

from ..harness.state import Action, ActionType, RiskLevel

HIGH_RISK_KEYWORDS: tuple[str, ...] = (
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

MEDIUM_RISK_KEYWORDS: tuple[str, ...] = (
    "edit",
    "update",
    "save",
    "rename",
    "share",
    "invite",
    "send",
    "schedule",
)


def _compile(keywords: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(
        re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE) for k in keywords
    )


_HIGH_RISK_PATTERNS: tuple[re.Pattern[str], ...] = _compile(HIGH_RISK_KEYWORDS)
_MEDIUM_RISK_PATTERNS: tuple[re.Pattern[str], ...] = _compile(MEDIUM_RISK_KEYWORDS)


def _anyMatch(patterns: tuple[re.Pattern[str], ...], haystacks: list[str]) -> bool:
    for pattern in patterns:
        for haystack in haystacks:
            if pattern.search(haystack):
                return True
    return False


def classifyRisk(action: Action, taskDescription: str = "") -> RiskLevel:
    if action.type == ActionType.FINISH:
        return RiskLevel.SAFE

    haystacks = [
        action.target or "",
        action.value or "",
        action.reasoning or "",
        taskDescription or "",
    ]

    if _anyMatch(_HIGH_RISK_PATTERNS, haystacks):
        return RiskLevel.HIGH

    if action.type in (ActionType.CLICK, ActionType.SELECT, ActionType.PRESS):
        if _anyMatch(_MEDIUM_RISK_PATTERNS, haystacks):
            return RiskLevel.MEDIUM

    if action.type == ActionType.FILL:
        lowerHaystacks = [h.lower() for h in haystacks]
        if any("password" in h or "ssn" in h for h in lowerHaystacks):
            return RiskLevel.HIGH

    if action.type == ActionType.NAVIGATE:
        return RiskLevel.LOW

    return RiskLevel.LOW
