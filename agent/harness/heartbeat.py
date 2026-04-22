"""Phase 7 wall-clock heartbeat gate.

Long autonomous runs magnify every failure mode, so the runner bounds
wall-clock runtime independently of step count. Two thresholds:

  * 5 minutes without a successful step raises an approval prompt,
    routed through the existing Neo4j :ActionApproval queue with
    reason="heartbeat". The HTMX dashboard surfaces the prompt; the
    user can extend or cancel.
  * 20 minutes cumulative wall-clock emits
    `completionReason="wallclock_heartbeat"` and terminates the loop.

The heartbeat reads its clock from a caller-provided `time_source` so
tests can fast-forward without `asyncio.sleep`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_SILENT_THRESHOLD_SECONDS = 300   # 5 minutes
DEFAULT_HARD_CAP_SECONDS = 1200          # 20 minutes


@dataclass
class HeartbeatDecision:
    action: str  # "continue", "prompt", "terminate"
    reason: str = ""


@dataclass
class HeartbeatTracker:
    startedAt: float = field(default_factory = time.monotonic)
    lastSuccessAt: float = field(default_factory = time.monotonic)
    silentThresholdSeconds: float = DEFAULT_SILENT_THRESHOLD_SECONDS
    hardCapSeconds: float = DEFAULT_HARD_CAP_SECONDS
    timeSource: Callable[[], float] = time.monotonic

    def recordSuccess(self) -> None:
        self.lastSuccessAt = self.timeSource()

    def check(self) -> HeartbeatDecision:
        now = self.timeSource()
        if now - self.startedAt >= self.hardCapSeconds:
            return HeartbeatDecision(
                action = "terminate",
                reason = "wallclock_heartbeat",
            )
        if now - self.lastSuccessAt >= self.silentThresholdSeconds:
            return HeartbeatDecision(
                action = "prompt",
                reason = "heartbeat",
            )
        return HeartbeatDecision(action = "continue")
