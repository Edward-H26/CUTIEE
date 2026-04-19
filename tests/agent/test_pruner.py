"""Unit tests for the temporal pruner."""
from __future__ import annotations

from agent.harness.state import Action, ActionType, ObservationStep
from agent.pruning.context_window import RecencyPruner
from agent.pruning.fg_bg_decomposer import allocateFgBgBudget
from agent.pruning.summarizer import ruleBasedSummary


def _hist(n: int) -> list[ObservationStep]:
    return [
        ObservationStep(
            index = i,
            url = f"http://example.com/p{i}",
            domMarkdown = "x" * 200,
            action = Action(type = ActionType.CLICK, target = f"#btn{i}"),
        )
        for i in range(n)
    ]


def test_emptyHistoryReturnsEmpty():
    pruned = RecencyPruner().prune([])
    assert pruned.rawHistoryLength == 0
    assert pruned.recent == []
    assert pruned.middle == []
    assert pruned.distantSummary == ""


def test_smallHistoryFitsInRecent():
    pruner = RecencyPruner(recencyWindow = 3)
    pruned = pruner.prune(_hist(2))
    assert len(pruned.recent) == 2
    assert pruned.middle == []


def test_15StepReductionBeats70Percent():
    pruner = RecencyPruner()
    ratio = pruner.reductionRatio(_hist(15))
    assert ratio >= 0.70


def test_distantSummaryMentionsActionTypes():
    distant = _hist(8)
    summary = ruleBasedSummary(distant)
    assert "click" in summary


def test_fgBgRatiosByRecency():
    b0 = allocateFgBgBudget(1000, 0)
    b1 = allocateFgBgBudget(1000, 1)
    b2 = allocateFgBgBudget(1000, 2)
    assert b0.foreground >= b1.foreground >= b2.foreground


def test_promptIncludesRecentMiddleAndDistant():
    pruner = RecencyPruner()
    pruned = pruner.prune(_hist(15))
    text = pruner.formatForPrompt(pruned)
    assert "[recent step" in text
    assert "[middle]" in text
    assert "[history-summary]" in text
