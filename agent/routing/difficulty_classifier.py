"""Heuristic difficulty classifier.

Returns one of EASY / MEDIUM / HARD. The classifier is intentionally
keyword-heavy because (a) the orchestrator can override via
`memoryEnhanced=True`, and (b) the confidence probe handles edge cases by
escalating after the fact. Spec note from plans/.../task-4.4: high-risk
keywords always yield HARD; >50 visible elements always yield HARD;
memory-enhanced downgrades by one tier.
"""
from __future__ import annotations

import enum

from agent.browser.dom_extractor import DOMState

HARD_KEYWORDS = (
    "purchase", "checkout", "payment", "delete", "remove account",
    "verify", "captcha", "two-factor", "subscribe",
)
EASY_KEYWORDS = ("click", "open", "go to", "navigate", "scroll", "search")


class Difficulty(str, enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


def classifyDifficulty(
    task: str,
    dom: DOMState | None,
    *,
    hasMemory: bool = False,
) -> Difficulty:
    text = (task or "").lower()
    elementCount = dom.elementCount if dom else 0

    if any(keyword in text for keyword in HARD_KEYWORDS):
        return Difficulty.HARD
    if elementCount > 50:
        return Difficulty.HARD

    if any(keyword in text for keyword in EASY_KEYWORDS) and elementCount <= 15:
        difficulty = Difficulty.EASY
    elif elementCount <= 30:
        difficulty = Difficulty.MEDIUM
    else:
        difficulty = Difficulty.HARD

    if hasMemory:
        difficulty = _downgrade(difficulty)

    return difficulty


def _downgrade(difficulty: Difficulty) -> Difficulty:
    if difficulty == Difficulty.HARD:
        return Difficulty.MEDIUM
    if difficulty == Difficulty.MEDIUM:
        return Difficulty.EASY
    return difficulty


def initialTierFor(difficulty: Difficulty) -> int:
    return {Difficulty.EASY: 1, Difficulty.MEDIUM: 2, Difficulty.HARD: 3}[difficulty]
