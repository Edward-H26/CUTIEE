"""Reflector — extract `LessonCandidate`s from a finished execution.

The reflector reads an `AgentState` (the full step trace) and emits a list
of structured lesson candidates. Each candidate has a content string, a
suggested memory type, a confidence score, and optional tags. The class can
be subclassed to plug in a real VLM-based reflector; the default heuristic
implementation is dependency-free so the pipeline can run end-to-end during
tests and offline demos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent.harness.state import ActionType, AgentState

PROCEDURAL_HINTS = ("step", "procedure", "workflow", "sequence", "click", "fill")
EPISODIC_HINTS = ("user", "asked", "prefers", "wants", "today", "this run")
SEMANTIC_HINTS = ("is at", "selector", "url", "always", "usually")


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

        for step in successfulSteps:
            if step.action is None:
                continue
            if step.action.type == ActionType.FINISH:
                continue
            content = (
                f"step_index={step.index} action={step.action.type.value} "
                f"target={step.action.target!r} "
                f"value={(step.action.value or '')!r}"
            )
            tags = [topic]
            if domain:
                tags.append(f"domain:{domain}")
            if step.action.risk.value == "high":
                tags.append("risk:high")
            lessons.append(
                LessonCandidate(
                    content = content,
                    memoryType = "procedural",
                    confidence = max(0.7, step.action.confidence or 0.7),
                    tags = tags,
                    topic = topic,
                    concept = step.action.type.value,
                )
            )

        if state.isComplete:
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


def _slugify(text: str) -> str:
    if not text:
        return "task"
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    return text.strip("-")[:48] or "task"
