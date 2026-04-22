"""Reflector — extract `LessonCandidate`s from a finished execution.

Two implementations:

  * `HeuristicReflector` (default, dependency-free) — walks the trajectory
    and emits structured candidates based on action types and outcomes.
    Cheap, deterministic, runs offline.

  * `LlmReflector` — calls Gemini with miramemoria's REFLECTOR_PROMPT,
    parses the JSON response, returns LessonCandidates. Richer lessons,
    costs ~1 Gemini call per task. Requires `GEMINI_API_KEY`.

Both implement the `Reflector` protocol below so the pipeline can swap
between them based on `CUTIEE_REFLECTOR=llm` (default `heuristic`).

Custom reflectors (e.g., a CU-specific reflector that outputs structured
action graphs) just need to implement `reflect(state) -> list[LessonCandidate]`.
This is the extensibility hook that lets the same pipeline serve chat
agents, CU agents, code agents, etc.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..harness.state import ActionType, AgentState

PROCEDURAL_HINTS = ("step", "procedure", "workflow", "sequence", "click", "fill")
EPISODIC_HINTS = ("user", "asked", "prefers", "wants", "today", "this run")
SEMANTIC_HINTS = ("is at", "selector", "url", "always", "usually")

# Phase 10 reflector credential scrubbing: regex patterns that match
# values that look like credentials, account numbers, or other PII that
# must not persist inside bullet content. Matching values are elided to
# `<redacted:N>` where N is the original length, and the bullet is
# flagged with is_credential=True so retrieval filters it out.
_CREDENTIAL_LIKE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 13-19 digits with optional dashes or spaces: the canonical
    # major-brand credit card range (Visa, Mastercard, Amex, Discover,
    # JCB, Diners, Maestro). Narrower than the old `\d{9,18}` bucket
    # which caught phone numbers, order ids, and epoch timestamps.
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    # SSN: strict 3-2-4 grouping only.
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # CVV/CVC: a 3-4 digit group that appears next to the keyword.
    re.compile(r"\b\d{3,4}\b(?=\s*(cvv|cvc))", re.IGNORECASE),
    # Routing number: nine digits explicitly labelled.
    re.compile(r"(?i)(?:routing|aba)[^\d]{0,6}\d{9}\b"),
    # Secret-like key=value pairs. These stay broad because a real
    # occurrence in bullet content almost always indicates a leak.
    re.compile(r"(?i)password\s*[=:]\s*\S+"),
    re.compile(r"(?i)secret\s*[=:]\s*\S+"),
    re.compile(r"(?i)token\s*[=:]\s*\S+"),
    re.compile(r"(?i)api[_-]?key\s*[=:]\s*\S+"),
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9_.\-]{16,}"),
)

_ACCOUNT_LIKE_TASK_MARKERS = (
    "account number",
    "ssn",
    "social security",
    "credit card",
    "cvv",
    "wire transfer",
    "routing number",
)


def _looksLikeCredential(value: str) -> bool:
    if not value:
        return False
    return any(pattern.search(value) for pattern in _CREDENTIAL_LIKE_PATTERNS)


def _redactValue(value: str) -> str:
    if not value:
        return value
    return f"<redacted:{len(value)}>"


def _taskDescriptionContainsAccountMarker(taskDescription: str) -> bool:
    if not taskDescription:
        return False
    lowered = taskDescription.lower()
    return any(marker in lowered for marker in _ACCOUNT_LIKE_TASK_MARKERS)

logger = logging.getLogger("cutiee.reflector")

# Ported verbatim from miramemoria/app/chat/ace_runtime.py:
# the REFLECTOR_PROMPT they hand to Gemini for lesson extraction.
REFLECTOR_SYSTEM_INSTRUCTION = (
    "You are a curation assistant. Output only valid JSON that matches the requested schema. "
    "Do not include markdown fences or explanatory prose."
)
REFLECTOR_PROMPT = """You are the Reflector in an Agentic Context Engineering system.

Your role is to analyze the execution trace and extract concrete, actionable lessons that can help improve future performance.

## Execution Trace
{trace}

## Task
{task_description}

## Outcome
{outcome}

## Instructions
Analyze the execution trace above and extract specific lessons:

1. Successful strategies that improved task completion
2. Failure modes or mistakes to avoid
3. Domain insights that should be remembered
4. Procedural patterns (action sequences) that should be reused

For each lesson:
- Be specific and concrete
- Keep it reusable across future tasks
- Avoid copying the action verbatim
- Keep it focused on one insight

Return JSON with this exact shape:
{{
  "lessons": [
    {{
      "content": "Specific lesson content",
      "type": "procedural" | "episodic" | "semantic",
      "tags": ["tag1", "tag2"],
      "confidence": 0.85
    }}
  ]
}}
"""

GENERIC_LESSON_PATTERNS = (
    "provide a clear answer like:",
    "when handling ",
    "the answer is ",
)


@dataclass
class LessonCandidate:
    content: str
    memoryType: str = "semantic"
    confidence: float = 0.7
    tags: list[str] = field(default_factory = list)
    topic: str = ""
    concept: str = ""
    replacementForBulletId: str | None = None
    metadata: dict[str, Any] = field(default_factory = dict)


class Reflector(Protocol):
    """Anything that can extract lessons from a finished `AgentState`.

    Plug in your own (chat-specific, code-specific, robotics-specific)
    by implementing this single method.
    """
    def reflect(self, state: AgentState) -> list[LessonCandidate]: ...


@dataclass
class HeuristicReflector:
    minConfidence: float = 0.7

    def reflect(self, state: AgentState) -> list[LessonCandidate]:
        if not state.history:
            return []
        lessons: list[LessonCandidate] = []
        domain = _domainFromUrl(state.history[0].url if state.history[0].url else "")
        topic = f"task:{_slugify(state.taskDescription)}"
        successfulSteps = [step for step in state.history if step.verificationOk and step.action]

        taskHasAccountMarker = _taskDescriptionContainsAccountMarker(state.taskDescription)
        for step in successfulSteps:
            if step.action is None:
                continue
            if step.action.type == ActionType.FINISH:
                continue
            # Computer Use steps carry pixel coordinates instead of CSS selectors;
            # capture them so the replay planner can rebuild a CU-compatible
            # action without falling back to an unparsable target string.
            extra = ""
            if step.action.coordinate is not None:
                cx, cy = step.action.coordinate
                extra += f" coordinate=({cx},{cy})"
            if step.action.keys:
                extra += f" keys={','.join(step.action.keys)}"
            if step.action.scrollDx or step.action.scrollDy:
                extra += f" scroll=({step.action.scrollDx},{step.action.scrollDy})"
            # Phase 10 reflector credential scrubbing: values that look
            # like credentials are elided and the bullet is flagged so
            # retrieval never surfaces it back to the model.
            rawValue = step.action.value or ""
            isCredential = _looksLikeCredential(rawValue) or step.action.risk.value == "high"
            safeValue = _redactValue(rawValue) if isCredential else rawValue
            content = (
                f"step_index={step.index} action={step.action.type.value} "
                f"target={step.action.target!r} "
                f"value={safeValue!r}"
                f"{extra}"
            )
            tags = [topic]
            if domain:
                tags.append(f"domain:{domain}")
            if step.action.risk.value == "high":
                tags.append("risk:high")
            if isCredential:
                tags.append("credential")
            candidate = LessonCandidate(
                content = content,
                memoryType = "procedural",
                confidence = max(0.7, step.action.confidence or 0.7),
                tags = tags,
                topic = topic,
                concept = step.action.type.value,
            )
            candidate.metadata["is_credential"] = isCredential
            lessons.append(candidate)

        if state.isComplete and not taskHasAccountMarker:
            # Phase 10: skip the episodic summary entirely when the task
            # description contains account-like markers so account numbers,
            # SSNs, or wire transfer details never land in memory.
            lessons.append(
                LessonCandidate(
                    content = (
                        f"Task '{state.taskDescription}' completed in "
                        f"{len(state.history)} step(s) with total cost ${state.totalCostUsd:.4f}"
                    ),
                    memoryType = "episodic",
                    confidence = 0.85 if state.isComplete else 0.6,
                    tags = [topic, "outcome:success" if state.isComplete else "outcome:fail"],
                    topic = topic,
                    concept = "outcome",
                )
            )

        if domain:
            lessons.append(
                LessonCandidate(
                    content = f"User has interacted with {domain} via task '{state.taskDescription}'.",
                    memoryType = "semantic",
                    confidence = 0.75,
                    tags = [f"domain:{domain}"],
                    topic = topic,
                    concept = "domain-affinity",
                )
            )

        return [lesson for lesson in lessons if lesson.confidence >= self.minConfidence]


def _domainFromUrl(url: str) -> str:
    if not url:
        return ""
    match = re.match(r"https?://([^/]+)/?", url)
    if match is None:
        return ""
    host = match.group(1)
    return host.split(":")[0]


from .text_utils import slugify as _slugify  # noqa: E402 - re-export for legacy call sites


@dataclass
class LlmReflector:
    """Gemini-driven Reflector — miramemoria's `_reflect_lessons` ported.

    Sends the execution trace to Gemini with a structured JSON-schema
    prompt asking for actionable lessons. Falls back to HeuristicReflector
    if `ACE_REFLECTION_ENABLED=false`, the API call fails, or the response
    can't be parsed.

    The fallback is a key reliability property: if Gemini is down or the
    user is offline, the agent still learns from the trace via heuristics.
    """
    apiKey: str | None = None
    modelId: str = "gemini-flash-latest"
    maxOutputTokens: int = 700
    temperature: float = 0.2
    minConfidence: float = 0.6
    fallback: HeuristicReflector = field(default_factory = HeuristicReflector)
    _client: Any = None

    def __post_init__(self) -> None:
        if not _envBool("ACE_REFLECTION_ENABLED", True):
            self._client = None
            return
        key = self.apiKey or os.environ.get("GEMINI_API_KEY")
        if not key:
            logger.warning(
                "LlmReflector: no GEMINI_API_KEY; will always fall back to heuristic"
            )
            self._client = None
            return
        try:
            from google import genai
            self._client = genai.Client(api_key = key)
        except Exception as exc:
            logger.warning("LlmReflector: client init failed (%s); falling back", exc)
            self._client = None

    def reflect(self, state: AgentState) -> list[LessonCandidate]:
        if self._client is None:
            return self.fallback.reflect(state)
        try:
            return self._reflectViaGemini(state)
        except Exception as exc:
            logger.warning("LlmReflector: Gemini call failed (%s); falling back", exc)
            return self.fallback.reflect(state)

    def _reflectViaGemini(self, state: AgentState) -> list[LessonCandidate]:
        from google.genai import types

        trace = self._formatTrace(state)
        outcome = "complete" if state.isComplete else "incomplete"
        if state.completionReason:
            outcome = f"{outcome} ({state.completionReason})"

        prompt = REFLECTOR_PROMPT.format(
            trace = trace,
            task_description = state.taskDescription,
            outcome = outcome,
        )
        response = self._client.models.generate_content(
            model = self.modelId,
            contents = prompt,
            config = types.GenerateContentConfig(
                system_instruction = REFLECTOR_SYSTEM_INSTRUCTION,
                temperature = self.temperature,
                max_output_tokens = self.maxOutputTokens,
                response_mime_type = "application/json",
            ),
        )
        rawText = (response.text or "").strip()
        return self._parseLessons(rawText, state)

    def _formatTrace(self, state: AgentState) -> str:
        lines = []
        for step in state.history:
            if step.action is None:
                continue
            extra = ""
            if step.action.coordinate:
                extra = f" coord={step.action.coordinate}"
            elif step.action.target:
                extra = f" target={step.action.target!r}"
            lines.append(
                f"step {step.index}: {step.action.type.value}{extra}"
                f"{' [FAILED]' if not step.verificationOk else ''}"
            )
        return "\n".join(lines) if lines else "(no steps recorded)"

    def _parseLessons(self, rawText: str, state: AgentState) -> list[LessonCandidate]:
        payload = _parseJsonLoose(rawText)
        if not isinstance(payload, dict):
            logger.debug("LlmReflector: response not a dict")
            return []
        lessons = payload.get("lessons")
        if not isinstance(lessons, list):
            logger.debug("LlmReflector: no lessons array in response")
            return []

        topic = f"task:{_slugify(state.taskDescription)}"
        domain = _domainFromUrl(state.history[0].url) if state.history else ""
        out: list[LessonCandidate] = []
        for raw in lessons:
            if not isinstance(raw, dict):
                continue
            content = (raw.get("content") or "").strip()
            if not content or _isGenericLesson(content):
                continue
            confidence = _clamp01(raw.get("confidence", 0.7))
            if confidence < self.minConfidence:
                continue
            memoryType = raw.get("type") or "semantic"
            if memoryType not in {"semantic", "episodic", "procedural"}:
                memoryType = "semantic"
            tags = list(raw.get("tags") or [])
            tags.append(topic)
            if domain:
                tags.append(f"domain:{domain}")
            out.append(LessonCandidate(
                content = content,
                memoryType = memoryType,
                confidence = confidence,
                tags = tags,
                topic = topic,
                concept = memoryType,
            ))
        return out


from .text_utils import parseJsonLoose as _parseJsonLoose  # noqa: E402


def _isGenericLesson(content: str) -> bool:
    lower = (content or "").strip().lower()
    if not lower or len(lower.split()) < 8:
        return True
    return any(p in lower for p in GENERIC_LESSON_PATTERNS)


def _clamp01(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.7
    return max(0.0, min(1.0, f))


def _envBool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def buildReflector(*, apiKey: str | None = None) -> Reflector:
    """Pick the right Reflector based on env.

    `CUTIEE_REFLECTOR=llm` → LlmReflector (with HeuristicReflector fallback)
    `CUTIEE_REFLECTOR=heuristic` (default) → HeuristicReflector
    """
    kind = os.environ.get("CUTIEE_REFLECTOR", "heuristic").lower()
    if kind == "llm":
        return LlmReflector(apiKey = apiKey)
    return HeuristicReflector()
