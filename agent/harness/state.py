"""Agent state dataclasses for CUTIEE.

The harness models the agent loop as a sequence of `ObservationStep`s. Each step
captures the prompt context the VLM saw, the `Action` it returned, the cost of
that decision, and the verification status. `AgentState` is the running record
that gets handed to the memory pipeline at the end of a task.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class ActionType(str, enum.Enum):
    # Browser-shell actions the runner emits directly.
    NAVIGATE = "navigate"
    WAIT = "wait"
    FINISH = "finish"
    APPROVE = "approve"
    # Pixel-coordinate actions returned by the Gemini Computer Use tool.
    CLICK_AT = "click_at"
    TYPE_AT = "type_at"
    KEY_COMBO = "key_combo"
    SCROLL_AT = "scroll_at"
    OPEN_BROWSER = "open_browser"
    # Legacy CSS-selector actions, retained for procedural-memory replay
    # of pre-CU runs. Not emitted by any current model; the runner ignores
    # them and they would fail at execute() time on a real browser.
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    SCROLL = "scroll"
    PRESS = "press"


class RiskLevel(str, enum.Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Action:
    type: ActionType
    target: str = ""
    value: str | None = None
    reasoning: str = ""
    model_used: str = ""
    tier: int = 0
    confidence: float = 0.0
    risk: RiskLevel = RiskLevel.SAFE
    cost_usd: float = 0.0
    requires_approval: bool = False
    # Pixel-coordinate fields used by the Computer Use tier. Optional so the
    # JSON-action tiers can stay unchanged.
    coordinate: tuple[int, int] | None = None
    keys: list[str] | None = None
    scrollDx: int = 0
    scrollDy: int = 0

    def isFinish(self) -> bool:
        return self.type == ActionType.FINISH

    def asDict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "target": self.target,
            "value": self.value,
            "reasoning": self.reasoning,
            "model_used": self.model_used,
            "tier": self.tier,
            "confidence": self.confidence,
            "risk": self.risk.value,
            "cost_usd": self.cost_usd,
            "coordinate": list(self.coordinate) if self.coordinate else None,
            "keys": self.keys,
            "scrollDx": self.scrollDx,
            "scrollDy": self.scrollDy,
        }


@dataclass
class ObservationStep:
    index: int
    url: str = ""
    domMarkdown: str = ""
    domHash: str = ""
    screenshotPath: str | None = None
    action: Action | None = None
    verificationOk: bool = True
    verificationNote: str = ""
    durationMs: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def shortSummary(self) -> str:
        if self.action is None:
            return f"step={self.index} url={self.url}"
        verdict = "ok" if self.verificationOk else "fail"
        return (
            f"step={self.index} action={self.action.type.value} "
            f"target={self.action.target!r} {verdict}"
        )


@dataclass
class AgentState:
    taskId: str
    userId: str
    taskDescription: str
    executionId: str = field(default_factory=lambda: str(uuid.uuid4()))
    history: list[ObservationStep] = field(default_factory=list)
    isComplete: bool = False
    completionReason: str = ""
    totalCostUsd: float = 0.0
    startedAt: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finishedAt: datetime | None = None
    replayed: bool = False
    templateId: str | None = None

    def appendStep(self, step: ObservationStep) -> None:
        self.history.append(step)
        if step.action is not None:
            self.totalCostUsd += step.action.cost_usd

    def stepCount(self) -> int:
        return len(self.history)

    def markComplete(self, reason: str) -> None:
        self.isComplete = True
        self.completionReason = reason
        self.finishedAt = datetime.now(timezone.utc)

    def lastNSteps(self, n: int) -> list[ObservationStep]:
        if n <= 0:
            return []
        return self.history[-n:]
