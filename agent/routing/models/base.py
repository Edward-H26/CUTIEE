"""Abstract VLM client interface used by every tier."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent.browser.dom_extractor import DOMState
from agent.harness.state import Action


@dataclass
class PredictionResult:
    action: Action
    confidence: float
    costUsd: float
    rawResponse: str = ""


class VLMClient(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def costPerMillionInputTokens(self) -> float:
        ...

    @property
    @abstractmethod
    def costPerMillionOutputTokens(self) -> float:
        ...

    @abstractmethod
    async def predictAction(
        self,
        task: str,
        dom: DOMState,
        prunedContext: str,
    ) -> PredictionResult:
        ...
