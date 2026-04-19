"""Qwen3.5 0.8B client backed by `llama-server`.

Three modes pack different prompt budgets so the same checkpoint can serve
all three router tiers. Tier-1 ("simple") sends only the task and a tiny
DOM excerpt. Tier-2 ("general") includes the pruned trajectory. Tier-3
("full_context") sends the full pruned context block.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

from agent.browser.dom_extractor import DOMState
from agent.harness.state import Action, ActionType
from agent.routing.confidence_probe import (
    confidenceFromHeuristic,
    confidenceFromLogprobs,
)
from agent.routing.models.base import PredictionResult, VLMClient

QWEN_SYSTEM_PROMPT = (
    "You are CUTIEE, a computer-use agent. Output ONLY a JSON object with keys "
    '"type" (click|fill|navigate|select|scroll|press|wait|finish), "target" '
    "(CSS selector or URL), optional \"value\" string, and optional "
    "\"reasoning\" string. No prose."
)


@dataclass
class QwenLocalClient(VLMClient):
    serverUrl: str
    mode: str = "general"
    label: str = "qwen3.5-0.8b"
    timeoutSeconds: float = 30.0
    maxTokens: int = 256

    @property
    def name(self) -> str:
        return f"{self.label}/{self.mode}"

    @property
    def costPerMillionInputTokens(self) -> float:
        return 0.0

    @property
    def costPerMillionOutputTokens(self) -> float:
        return 0.0

    def _buildPrompt(self, task: str, dom: DOMState, prunedContext: str) -> str:
        domSlice = dom.markdown or ""
        if self.mode == "simple":
            domSlice = domSlice[:600]
            history = ""
        elif self.mode == "general":
            domSlice = domSlice[:2400]
            history = prunedContext[:1200]
        else:
            history = prunedContext[:4800]
        body = f"# Task\n{task}\n\n# Page\n{domSlice}\n"
        if history:
            body += f"\n# Recent\n{history}\n"
        body += "\n# Reply\n"
        return body

    async def predictAction(
        self,
        task: str,
        dom: DOMState,
        prunedContext: str,
    ) -> PredictionResult:
        prompt = self._buildPrompt(task, dom, prunedContext)
        payload: dict[str, object] = {
            "prompt": prompt,
            "n_predict": self.maxTokens,
            "temperature": 0.2,
            "stop": ["</json>", "\n\n"],
            "system_prompt": QWEN_SYSTEM_PROMPT,
            "logprobs": 5,
        }
        async with httpx.AsyncClient(timeout = self.timeoutSeconds) as client:
            response = await client.post(f"{self.serverUrl}/completion", json = payload)
            response.raise_for_status()
            data = response.json()

        rawText = (data.get("content") or "").strip()
        action, parsed = _parseAction(rawText, self.name)
        confidence = confidenceFromHeuristic(
            parsed = parsed,
            hasTarget = bool(action.target),
            hasReasoning = bool(action.reasoning),
        )
        logprobs = _extractLogprobs(data.get("completion_probabilities") or [])
        if logprobs:
            confidence = max(confidence, confidenceFromLogprobs(logprobs))
        action.confidence = confidence
        action.cost_usd = 0.0
        return PredictionResult(
            action = action,
            confidence = confidence,
            costUsd = 0.0,
            rawResponse = rawText,
        )


def buildQwenClientFromEnv(mode: str) -> QwenLocalClient:
    serverUrl = os.environ.get("QWEN_SERVER_URL")
    if not serverUrl:
        raise RuntimeError("QWEN_SERVER_URL is required for Qwen tier clients.")
    return QwenLocalClient(serverUrl = serverUrl, mode = mode)


def _parseAction(rawText: str, modelLabel: str) -> tuple[Action, bool]:
    payload: dict[str, object] | None = None
    try:
        payload = json.loads(rawText)
    except (TypeError, ValueError):
        startIdx = rawText.find("{")
        endIdx = rawText.rfind("}")
        if 0 <= startIdx < endIdx:
            try:
                payload = json.loads(rawText[startIdx : endIdx + 1])
            except (TypeError, ValueError):
                payload = None

    if not isinstance(payload, dict):
        return (
            Action(
                type = ActionType.FINISH,
                reasoning = "qwen produced unparseable response",
                model_used = modelLabel,
            ),
            False,
        )

    typeRaw = str(payload.get("type") or "finish").lower()
    try:
        actionType = ActionType(typeRaw)
    except ValueError:
        actionType = ActionType.FINISH

    return (
        Action(
            type = actionType,
            target = str(payload.get("target") or ""),
            value = (str(payload["value"]) if "value" in payload and payload["value"] is not None else None),
            reasoning = str(payload.get("reasoning") or ""),
            model_used = modelLabel,
        ),
        True,
    )


def _extractLogprobs(probabilities: list[dict[str, object]]) -> list[float]:
    out: list[float] = []
    for entry in probabilities:
        topProbs = entry.get("probs") if isinstance(entry, dict) else None
        if not isinstance(topProbs, list) or not topProbs:
            continue
        firstProb = topProbs[0]
        if isinstance(firstProb, dict):
            value = firstProb.get("logprob") or firstProb.get("prob")
            if isinstance(value, (int, float)):
                out.append(float(value))
    return out
