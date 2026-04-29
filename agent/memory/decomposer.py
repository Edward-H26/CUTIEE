"""LlmActionDecomposer — Gemini decomposes a task into an ActionNode chain.

Phase 2 of the miramemoria-parity plan. After a successful run, OR before
a new task starts, the decomposer asks Gemini to break the task
description into named atomic steps:

    Input:  "make column C be the sum of column A and B in this Sheet"
    Output: ProcedureGraph(nodes=[
        ActionNode(action_type="navigate",  target="<sheet url>",     description="open the spreadsheet"),
        ActionNode(action_type="click_at",  coord=(384, 120),         description="locate column C header"),
        ActionNode(action_type="type_at",   value="=SUM(A:B)",        description="enter the sum formula"),
        ActionNode(action_type="key_combo", value="Enter",            description="commit the formula"),
    ])

These nodes get persisted and can be matched against future tasks via
the SubgraphMatcher (Phase 3).
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

from .action_graph import ActionEdge, ActionNode, ProcedureGraph
from . import local_llm

logger = logging.getLogger("cutiee.decomposer")

DECOMPOSER_SYSTEM_INSTRUCTION = (
    "You are a task decomposition assistant. Output only valid JSON. "
    "Decompose the user's task into the minimal sequence of atomic browser "
    "actions a Computer Use agent would execute."
)

DECOMPOSER_PROMPT = """Decompose this browser-automation task into a sequence of atomic steps.

## Task
{task_description}

## Initial URL (if any)
{initial_url}

## Output Schema

Return JSON with this exact shape:
{{
  "steps": [
    {{
      "action_type": "navigate" | "click_at" | "type_at" | "key_combo" | "scroll_at" | "wait" | "finish",
      "target": "URL or selector or element description",
      "value": "text to type, key to press, or empty",
      "description": "one-line human-readable label"
    }}
  ]
}}

## Rules
- Each step is ONE atomic action — no compound steps
- Use coordinate-free descriptions in `target` (e.g., "the formula bar", "column C header")
  — the runner will resolve them via Computer Use at execution time
- Skip implicit waits unless the task requires explicit timing
- The last step should typically be `{{"action_type": "finish", ...}}`
- Aim for 3-10 steps. Be concise.
"""


@dataclass
class LlmActionDecomposer:
    """Calls Gemini to break a task description into ActionNode chain.

    Best-effort: if Gemini is unavailable or returns garbage, returns an
    empty `ProcedureGraph` so the caller can fall back to direct CU.
    """
    apiKey: str | None = None
    modelId: str = "gemini-flash-latest"
    maxOutputTokens: int = 1200
    temperature: float = 0.1
    _client: Any = None

    def __post_init__(self) -> None:
        key = self.apiKey or os.environ.get("GEMINI_API_KEY")
        if not key:
            self._client = None
            return
        try:
            from google import genai
            self._client = genai.Client(api_key = key)
        except Exception as exc:
            logger.warning("LlmActionDecomposer init failed: %s", exc)
            self._client = None

    def decompose(
        self,
        *,
        userId: str,
        taskDescription: str,
        initialUrl: str = "",
    ) -> ProcedureGraph:
        if local_llm.shouldUseLocalLlmForUrl(initialUrl):
            try:
                graph = self._decomposeViaLocalQwen(userId, taskDescription, initialUrl)
                if graph.nodes:
                    return graph
            except Exception as exc:
                logger.warning("LlmActionDecomposer local-Qwen call failed: %s", exc)
        if self._client is None:
            return _emptyGraph(userId, taskDescription)
        try:
            return self._decomposeViaGemini(userId, taskDescription, initialUrl)
        except Exception as exc:
            logger.warning("LlmActionDecomposer Gemini call failed: %s", exc)
            return _emptyGraph(userId, taskDescription)

    def _decomposeViaLocalQwen(
        self, userId: str, taskDescription: str, initialUrl: str,
    ) -> ProcedureGraph:
        prompt = DECOMPOSER_PROMPT.format(
            task_description = taskDescription,
            initial_url = initialUrl or "(none — agent infers)",
        )
        rawText = local_llm.generateText(
            systemInstruction = DECOMPOSER_SYSTEM_INSTRUCTION,
            userPrompt = prompt,
            maxNewTokens = self.maxOutputTokens,
        ) or ""
        return self._parseGraph(rawText, userId, taskDescription)

    def _decomposeViaGemini(
        self, userId: str, taskDescription: str, initialUrl: str,
    ) -> ProcedureGraph:
        from google.genai import types

        prompt = DECOMPOSER_PROMPT.format(
            task_description = taskDescription,
            initial_url = initialUrl or "(none — agent infers)",
        )
        response = self._client.models.generate_content(
            model = self.modelId,
            contents = prompt,
            config = types.GenerateContentConfig(
                system_instruction = DECOMPOSER_SYSTEM_INSTRUCTION,
                temperature = self.temperature,
                max_output_tokens = self.maxOutputTokens,
                response_mime_type = "application/json",
            ),
        )
        rawText = (response.text or "").strip()
        return self._parseGraph(rawText, userId, taskDescription)

    def _parseGraph(
        self, rawText: str, userId: str, taskDescription: str,
    ) -> ProcedureGraph:
        payload = _parseJsonLoose(rawText)
        if not isinstance(payload, dict):
            return _emptyGraph(userId, taskDescription)
        steps = payload.get("steps")
        if not isinstance(steps, list) or not steps:
            return _emptyGraph(userId, taskDescription)

        procedureId = str(uuid.uuid4())
        nodes: list[ActionNode] = []
        edges: list[ActionEdge] = []
        for raw in steps:
            if not isinstance(raw, dict):
                continue
            actionType = (raw.get("action_type") or "").strip()
            if not actionType:
                continue
            node = ActionNode(
                action_type = actionType,
                target = (raw.get("target") or "").strip(),
                value = (raw.get("value") or "").strip(),
                description = (raw.get("description") or "").strip(),
            )
            nodes.append(node)

        for i, current in enumerate(nodes[:-1]):
            edges.append(ActionEdge(
                source_id = current.id,
                target_id = nodes[i + 1].id,
                procedure_id = procedureId,
                sequence_index = i,
            ))

        return ProcedureGraph(
            procedure_id = procedureId,
            user_id = userId,
            task_description = taskDescription,
            nodes = nodes,
            edges = edges,
            metadata = {"topic_slug": _slugify(taskDescription)},
        )


def _emptyGraph(userId: str, taskDescription: str) -> ProcedureGraph:
    return ProcedureGraph(
        procedure_id = str(uuid.uuid4()),
        user_id = userId,
        task_description = taskDescription,
    )


from .text_utils import parseJsonLoose as _parseJsonLoose, slugify as _slugify  # noqa: E402
