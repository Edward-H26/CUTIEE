"""Temporal recency pruner for text-context LLM agents.

Self-contained module; not used by CUTIEE's CU runner (which sends
screenshots, not text history) but kept as an importable utility for
DOM-based or other text-context agents that need to bound their
prompt size while preserving the most-recent steps verbatim.

Three-zone schedule (from the March 2026 GUI agent paper):

  * Recent N=3 steps  → full DOM + action + reasoning kept verbatim
  * Middle 3 steps    → action text only (one line per step)
  * Distant tail      → deterministic rollup via `ruleBasedSummary`

Empirical reduction on a 15-step trajectory: ~80%.

Standalone usage:

    from cutiee_ace import RecencyPruner, PrunedContext

    pruner = RecencyPruner(recencyWindow=3, middleWindow=3)
    pruned = pruner.prune(state.history)
    prompt_block = pruner.formatForPrompt(pruned)
    print(f"Reduction: {pruner.reductionRatio(state.history) * 100:.0f}%")
"""
from .context_window import (
    DEFAULT_MIDDLE_WINDOW,
    DEFAULT_RECENCY_WINDOW,
    PrunedContext,
    RecencyPruner,
    estimateTokens,
)
from .fg_bg_decomposer import TokenBudget, allocateFgBgBudget
from .summarizer import ruleBasedSummary

__all__ = [
    "DEFAULT_MIDDLE_WINDOW",
    "DEFAULT_RECENCY_WINDOW",
    "PrunedContext",
    "RecencyPruner",
    "TokenBudget",
    "allocateFgBgBudget",
    "estimateTokens",
    "ruleBasedSummary",
]
