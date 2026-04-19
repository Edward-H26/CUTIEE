"""Unit tests for the routing layer."""
from __future__ import annotations

import asyncio

from agent.browser.dom_extractor import DOMState
from agent.harness.state import Action, ActionType
from agent.routing.confidence_probe import (
    confidenceFromHeuristic,
    confidenceFromLogprobs,
)
from agent.routing.difficulty_classifier import (
    Difficulty,
    classifyDifficulty,
    initialTierFor,
)
from agent.routing.models.mock import MockVLMClient
from agent.routing.router import AdaptiveRouter


def _client(label: str, confidence: float, cost: float) -> MockVLMClient:
    return MockVLMClient(
        label = label,
        actionsToReturn = [Action(type = ActionType.CLICK, target = "#submit")],
        fixedConfidence = confidence,
        fixedCostUsd = cost,
    )


def _dom(elementCount: int = 5) -> DOMState:
    return DOMState(url = "http://x.com", title = "x", markdown = "# x", elementCount = elementCount)


def test_difficultyHardOnRiskKeyword():
    assert classifyDifficulty("delete my account", _dom(5)) == Difficulty.HARD


def test_difficultyHardOnLargePage():
    assert classifyDifficulty("click ok", _dom(80)) == Difficulty.HARD


def test_difficultyEasyOnSimpleClick():
    assert classifyDifficulty("click submit", _dom(5)) == Difficulty.EASY


def test_difficultyDowngradeWithMemory():
    assert classifyDifficulty("complex task", _dom(45), hasMemory = True) == Difficulty.MEDIUM


def test_initialTierMap():
    assert initialTierFor(Difficulty.EASY) == 1
    assert initialTierFor(Difficulty.MEDIUM) == 2
    assert initialTierFor(Difficulty.HARD) == 3


def test_confidenceFromHeuristic():
    high = confidenceFromHeuristic(parsed = True, hasTarget = True, hasReasoning = True)
    low = confidenceFromHeuristic(parsed = False, hasTarget = False, hasReasoning = False)
    assert abs(high - 1.0) < 1e-9
    assert abs(low - 0.5) < 1e-9


def test_confidenceFromLogprobsBounded():
    assert 0.0 <= confidenceFromLogprobs([-0.5, -0.3, -0.7]) <= 1.0
    assert confidenceFromLogprobs([]) == 0.5


def test_routerEscalatesOnLowConfidence():
    router = AdaptiveRouter(
        tier1 = _client("t1", 0.4, 0.001),
        tier2 = _client("t2", 0.6, 0.005),
        tier3 = _client("t3", 0.9, 0.02),
    )
    decision = asyncio.run(
        router.routeAndPredict(task = "click submit", dom = _dom(5), prunedContext = "")
    )
    assert decision.tier == 3
    assert decision.escalations == 2
    assert abs(decision.cumulativeCostUsd - 0.026) < 1e-6
    assert decision.tierClientNames == ["t1", "t2", "t3"]


def test_routerStopsAtFirstSatisfiedTier():
    router = AdaptiveRouter(
        tier1 = _client("t1", 0.95, 0.001),
        tier2 = _client("t2", 0.6, 0.005),
        tier3 = _client("t3", 0.9, 0.02),
    )
    decision = asyncio.run(
        router.routeAndPredict(task = "click submit", dom = _dom(5), prunedContext = "")
    )
    assert decision.tier == 1
    assert decision.escalations == 0
    assert decision.cumulativeCostUsd == 0.001
