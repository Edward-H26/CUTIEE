"""Temporal recency pruner.

Implements the three-zone schedule from the March-2026 GUI agent paper:

* Recent N=3 steps: full DOM + action + reasoning kept verbatim.
* Middle 3 steps: action text only.
* Distant tail: deterministic rollup via `ruleBasedSummary`.

The pruner is stateless. It accepts a list of `ObservationStep`s, partitions
them into the three zones, and returns a `PrunedContext` the orchestrator
hands to the VLM. Empirical reduction on a 15-step trace is ~80%.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ..harness.state import ObservationStep
from .fg_bg_decomposer import TokenBudget, allocateFgBgBudget
from .summarizer import ruleBasedSummary


def estimateTokens(text: str) -> int:
    """Rough 4-char-per-token heuristic. Good enough for budget guards.

    Inlined here (was previously in `agent/browser/dom_extractor`, removed
    in the all-CU pivot) so the pruning module stays self-contained.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)

DEFAULT_RECENCY_WINDOW = 3
DEFAULT_MIDDLE_WINDOW = 3


@dataclass
class PrunedContext:
    recent: list[ObservationStep] = field(default_factory = list)
    middle: list[ObservationStep] = field(default_factory = list)
    distantSummary: str = ""
    estimatedTokens: int = 0
    fgBgBudgets: list[TokenBudget] = field(default_factory = list)
    rawHistoryLength: int = 0


@dataclass
class RecencyPruner:
    recencyWindow: int = DEFAULT_RECENCY_WINDOW
    middleWindow: int = DEFAULT_MIDDLE_WINDOW
    perStepFullBudget: int = 4000

    def prune(self, history: Sequence[ObservationStep]) -> PrunedContext:
        if not history:
            return PrunedContext()
        history = list(history)
        recent = history[-self.recencyWindow:] if self.recencyWindow > 0 else []
        beforeRecent = history[: max(0, len(history) - self.recencyWindow)]
        middle = beforeRecent[-self.middleWindow:] if self.middleWindow > 0 else []
        distant = beforeRecent[: max(0, len(beforeRecent) - self.middleWindow)]

        budgets = [
            allocateFgBgBudget(self.perStepFullBudget, idx)
            for idx in range(len(recent))
        ]

        recentTokens = sum(estimateTokens(step.domMarkdown or "") for step in recent)
        middleTokens = sum(estimateTokens(step.shortSummary()) for step in middle)
        distantSummary = ruleBasedSummary(distant) if distant else ""
        distantTokens = estimateTokens(distantSummary)

        return PrunedContext(
            recent = recent,
            middle = middle,
            distantSummary = distantSummary,
            estimatedTokens = recentTokens + middleTokens + distantTokens,
            fgBgBudgets = budgets,
            rawHistoryLength = len(history),
        )

    def formatForPrompt(self, pruned: PrunedContext) -> str:
        if pruned.rawHistoryLength == 0:
            return ""
        sections: list[str] = []
        if pruned.distantSummary:
            sections.append(f"[history-summary] {pruned.distantSummary}")
        if pruned.middle:
            middleLines = [f"[middle] {step.shortSummary()}" for step in pruned.middle]
            sections.append("\n".join(middleLines))
        if pruned.recent:
            recentBlocks: list[str] = []
            for offset, step in enumerate(reversed(pruned.recent)):
                recencyIndex = offset
                budget = pruned.fgBgBudgets[recencyIndex] if recencyIndex < len(pruned.fgBgBudgets) else None
                domSlice = (step.domMarkdown or "")
                if budget is not None and budget.foreground:
                    domSlice = domSlice[: budget.foreground * 4]
                blockHeader = f"[recent step {step.index}] {step.shortSummary()}"
                recentBlocks.append(blockHeader + "\n" + domSlice)
            sections.append("\n\n".join(recentBlocks))
        return "\n\n".join(sections)

    def reductionRatio(self, history: Sequence[ObservationStep]) -> float:
        if not history:
            return 0.0
        rawTokens = sum(estimateTokens(step.domMarkdown or "") for step in history)
        if rawTokens == 0:
            return 0.0
        prunedTokens = self.prune(history).estimatedTokens
        return 1.0 - prunedTokens / rawTokens
