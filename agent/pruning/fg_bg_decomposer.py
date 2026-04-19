"""Foreground-background token budget allocator.

Recent screenshots get a 70/30 split (heavy foreground emphasis); older
screenshots collapse toward 50/50 because the agent benefits more from
ambient context the further back we look. The function returns integer
token counts so callers can use them directly to size truncations.
"""
from __future__ import annotations

from dataclasses import dataclass

FG_RATIO_BY_RECENCY: dict[int, float] = {
    0: 0.70,
    1: 0.60,
    2: 0.50,
}
DEFAULT_FG_RATIO = 0.50


@dataclass(frozen = True)
class TokenBudget:
    foreground: int
    background: int


def allocateFgBgBudget(totalTokens: int, recencyIndex: int) -> TokenBudget:
    if totalTokens <= 0:
        return TokenBudget(foreground = 0, background = 0)
    ratio = FG_RATIO_BY_RECENCY.get(max(recencyIndex, 0), DEFAULT_FG_RATIO)
    fg = int(totalTokens * ratio)
    bg = totalTokens - fg
    return TokenBudget(foreground = fg, background = bg)
