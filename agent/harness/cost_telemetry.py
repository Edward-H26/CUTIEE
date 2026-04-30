"""Phase 13 per-step cost telemetry.

Emits a structured record for every step so the dashboard can chart
cost drift without having to re-derive numbers from the audit. The
record goes into the audit stream (as a debug-level log line today)
and can be redirected to Neo4j or the HTMX dashboard without changing
the caller.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger("cutiee.cost_telemetry")


@dataclass(frozen=True)
class StepCost:
    stepIndex: int
    backend: str
    modelId: str
    inputTokens: int
    outputTokens: int
    costUsd: float
    cumulativeUsd: float


def emitStepCost(cost: StepCost) -> None:
    payload = {
        "step": cost.stepIndex,
        "backend": cost.backend,
        "model": cost.modelId,
        "input_tokens": cost.inputTokens,
        "output_tokens": cost.outputTokens,
        "usd": round(cost.costUsd, 6),
        "cumulative_usd": round(cost.cumulativeUsd, 6),
    }
    logger.info("cost %s", json.dumps(payload, sort_keys=True))


@dataclass(frozen=True)
class TaskCost:
    userId: str
    executionId: str
    backend: str
    totalUsd: float
    stepCount: int
    replayHitCount: int


def emitTaskCost(cost: TaskCost) -> None:
    savedViaReplay = cost.replayHitCount > 0
    payload = {
        "execution_id": cost.executionId,
        "user_id": cost.userId,
        "backend": cost.backend,
        "total_usd": round(cost.totalUsd, 6),
        "steps": cost.stepCount,
        "replay_hits": cost.replayHitCount,
        "saved_via_replay": savedViaReplay,
    }
    logger.info("task_cost %s", json.dumps(payload, sort_keys=True))
