"""Adaptive three-tier router with confidence escalation.

Algorithm:

1. Pick initial tier from `classifyDifficulty(task, dom, has_memory)`.
2. Call the tier's client.
3. If the returned confidence is below `THRESHOLDS[tier]`, escalate to the
   next tier and call again. Stop at tier 3.
4. Return a `RoutingDecision` with the final prediction, the tier used,
   and the cumulative cost across all tries.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from agent.browser.dom_extractor import DOMState
from agent.routing.confidence_probe import confidenceFromHeuristic
from agent.routing.difficulty_classifier import (
    Difficulty,
    classifyDifficulty,
    initialTierFor,
)
from agent.routing.models.base import PredictionResult, VLMClient

DEFAULT_THRESHOLDS: dict[int, float] = {1: 0.75, 2: 0.65, 3: 0.50}


@dataclass
class RoutingDecision:
    prediction: PredictionResult
    tier: int
    difficulty: Difficulty
    escalations: int = 0
    cumulativeCostUsd: float = 0.0
    tierClientNames: list[str] = field(default_factory = list)


@dataclass
class AdaptiveRouter:
    tier1: VLMClient
    tier2: VLMClient
    tier3: VLMClient
    thresholds: dict[int, float] = field(default_factory = lambda: dict(DEFAULT_THRESHOLDS))

    def __post_init__(self) -> None:
        for key in (1, 2, 3):
            envVar = f"CUTIEE_CONFIDENCE_THRESHOLD_TIER{key}"
            override = os.environ.get(envVar)
            if override:
                try:
                    self.thresholds[key] = float(override)
                except ValueError:
                    pass

    async def routeAndPredict(
        self,
        *,
        task: str,
        dom: DOMState,
        prunedContext: str,
        memoryEnhanced: bool = False,
        forceTier: int | None = None,
    ) -> RoutingDecision:
        difficulty = classifyDifficulty(task, dom, hasMemory = memoryEnhanced)
        startingTier = forceTier or initialTierFor(difficulty)

        cumulativeCost = 0.0
        clientsUsed: list[str] = []
        escalations = 0
        finalPrediction: PredictionResult | None = None

        currentTier = startingTier
        while currentTier <= 3:
            client = self._tierClient(currentTier)
            prediction = await client.predictAction(task, dom, prunedContext)
            cumulativeCost += prediction.costUsd
            clientsUsed.append(client.name)

            confidence = prediction.confidence
            if not confidence:
                confidence = confidenceFromHeuristic(
                    parsed = bool(prediction.action.target),
                    hasTarget = bool(prediction.action.target),
                    hasReasoning = bool(prediction.action.reasoning),
                )
                prediction.action.confidence = confidence
                prediction.confidence = confidence

            prediction.action.tier = currentTier
            prediction.action.cost_usd = cumulativeCost

            finalPrediction = prediction
            threshold = self.thresholds.get(currentTier, 0.0)
            if confidence >= threshold or currentTier == 3:
                break

            currentTier += 1
            escalations += 1

        if finalPrediction is None:
            raise RuntimeError("Routing produced no prediction.")
        return RoutingDecision(
            prediction = finalPrediction,
            tier = currentTier,
            difficulty = difficulty,
            escalations = escalations,
            cumulativeCostUsd = cumulativeCost,
            tierClientNames = clientsUsed,
        )

    def _tierClient(self, tier: int) -> VLMClient:
        if tier == 1:
            return self.tier1
        if tier == 2:
            return self.tier2
        return self.tier3
