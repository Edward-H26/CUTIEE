"""Gemini 3.1 client used by the production tier.

The production deployment runs three different Gemini variants for the
three router tiers. The pricing table is approximate; update it when Google
publishes final 3.1 pricing.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from agent.browser.dom_extractor import DOMState
from agent.harness.state import Action, ActionType
from agent.routing.confidence_probe import confidenceFromHeuristic
from agent.routing.models.base import PredictionResult, VLMClient

PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-lite": (0.075, 0.30),
    "gemini-3.1-flash": (0.15, 0.60),
    "gemini-3.1-pro": (1.25, 5.00),
}

SYSTEM_PROMPT = (
    "You are CUTIEE, a computer-use agent. Reply ONLY with a JSON object: "
    '{"type": "click|fill|navigate|select|scroll|press|wait|finish", '
    '"target": "CSS selector or URL", "value": optional, "reasoning": optional}.'
)


@dataclass
class GeminiCloudClient(VLMClient):
    modelId: str
    apiKey: str | None = None
    temperature: float = 0.2
    maxOutputTokens: int = 256
    _client: object | None = None

    def __post_init__(self) -> None:
        key = self.apiKey or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY required for GeminiCloudClient. No fallback."
            )
        if self.modelId not in PRICING_PER_MILLION:
            raise RuntimeError(
                f"Unknown Gemini model id {self.modelId!r}. Update PRICING_PER_MILLION."
            )
        self.apiKey = key
        from google import genai

        self._client = genai.Client(api_key = key)

    @property
    def name(self) -> str:
        return self.modelId

    @property
    def costPerMillionInputTokens(self) -> float:
        return PRICING_PER_MILLION[self.modelId][0]

    @property
    def costPerMillionOutputTokens(self) -> float:
        return PRICING_PER_MILLION[self.modelId][1]

    async def predictAction(
        self,
        task: str,
        dom: DOMState,
        prunedContext: str,
    ) -> PredictionResult:
        from google.genai import types

        prompt = (
            f"Task: {task}\n\nCurrent page:\n{dom.markdown}\n\n"
            f"Prior context:\n{prunedContext}\n\nNext action JSON:"
        )
        client = self._client
        if client is None:
            raise RuntimeError("Gemini client failed to initialise.")
        response = await client.aio.models.generate_content(  # type: ignore[attr-defined]
            model = self.modelId,
            contents = prompt,
            config = types.GenerateContentConfig(
                system_instruction = SYSTEM_PROMPT,
                temperature = self.temperature,
                max_output_tokens = self.maxOutputTokens,
                response_mime_type = "application/json",
            ),
        )
        text = (response.text or "").strip()
        action, parsed = _parseGeminiResponse(text, self.modelId)
        confidence = confidenceFromHeuristic(
            parsed = parsed,
            hasTarget = bool(action.target),
            hasReasoning = bool(action.reasoning),
        )
        usage = getattr(response, "usage_metadata", None)
        inputTokens = getattr(usage, "prompt_token_count", 0) or 0
        outputTokens = getattr(usage, "candidates_token_count", 0) or 0
        cost = (
            inputTokens / 1_000_000 * self.costPerMillionInputTokens
            + outputTokens / 1_000_000 * self.costPerMillionOutputTokens
        )
        action.confidence = confidence
        action.cost_usd = cost
        action.model_used = self.modelId
        return PredictionResult(
            action = action,
            confidence = confidence,
            costUsd = cost,
            rawResponse = text,
        )


def _parseGeminiResponse(text: str, modelId: str) -> tuple[Action, bool]:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return (
            Action(type = ActionType.FINISH, reasoning = "gemini parse error", model_used = modelId),
            False,
        )
    if not isinstance(payload, dict):
        return (
            Action(type = ActionType.FINISH, reasoning = "gemini non-object", model_used = modelId),
            False,
        )
    try:
        actionType = ActionType(str(payload.get("type") or "finish").lower())
    except ValueError:
        actionType = ActionType.FINISH
    return (
        Action(
            type = actionType,
            target = str(payload.get("target") or ""),
            value = str(payload["value"]) if payload.get("value") is not None else None,
            reasoning = str(payload.get("reasoning") or ""),
            model_used = modelId,
        ),
        True,
    )
