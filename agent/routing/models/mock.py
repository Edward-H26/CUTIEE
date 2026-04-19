"""Deterministic VLM stand-in used by tests, Phase-1 demos, and the Render
fallback when GEMINI_API_KEY is misconfigured.

Records every (task, dom, pruned_context) triple it sees so tests can assert
that pruning, retrieval, and routing all wired correctly. Returns the next
scripted action from `actionsToReturn`; when the script is exhausted it
returns `Action(type=FINISH)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.browser.dom_extractor import DOMState
from agent.harness.state import Action, ActionType
from agent.routing.models.base import PredictionResult, VLMClient


@dataclass
class MockVLMClient(VLMClient):
    label: str = "mock"
    actionsToReturn: list[Action] = field(default_factory = list)
    fixedConfidence: float = 0.85
    fixedCostUsd: float = 0.0
    lastTask: str = ""
    lastDom: DOMState | None = None
    lastPrunedContext: str = ""
    callCount: int = 0

    @property
    def name(self) -> str:
        return self.label

    @property
    def costPerMillionInputTokens(self) -> float:
        return 0.0

    @property
    def costPerMillionOutputTokens(self) -> float:
        return 0.0

    async def predictAction(
        self,
        task: str,
        dom: DOMState,
        prunedContext: str,
    ) -> PredictionResult:
        self.lastTask = task
        self.lastDom = dom
        self.lastPrunedContext = prunedContext
        self.callCount += 1
        if self.actionsToReturn:
            action = self.actionsToReturn.pop(0)
        else:
            action = Action(type = ActionType.FINISH, reasoning = "mock script exhausted")
        action.model_used = self.label
        action.confidence = self.fixedConfidence
        action.cost_usd = self.fixedCostUsd
        return PredictionResult(
            action = action,
            confidence = self.fixedConfidence,
            costUsd = self.fixedCostUsd,
            rawResponse = "mock",
        )
