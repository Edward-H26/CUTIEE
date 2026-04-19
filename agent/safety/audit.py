"""Audit writer that turns each agent step into an immutable `:AuditEntry`.

The orchestrator calls `writeAuditEntry` after every step; the function
formats a row and hands it to `apps.audit.repo.append_audit`. Persisting
through the repo (rather than in-line Cypher here) keeps the database surface
in one place and lets us swap the storage backend later if needed.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from ..harness.state import ObservationStep


@dataclass
class AuditPayload:
    id: str
    user_id: str
    task_id: str
    execution_id: str
    step_index: int
    timestamp: str
    action: str
    target: str
    value: str
    reasoning: str
    model: str
    tier: int
    cost_usd: float
    risk: str
    approval_status: str
    verification_ok: bool

    def asDict(self) -> dict[str, Any]:
        return asdict(self)


def buildAuditPayload(
    *,
    userId: str,
    taskId: str,
    executionId: str,
    step: ObservationStep,
    approvalStatus: str = "auto",
) -> AuditPayload:
    action = step.action
    return AuditPayload(
        id = str(uuid.uuid4()),
        user_id = str(userId),
        task_id = str(taskId),
        execution_id = str(executionId),
        step_index = step.index,
        timestamp = (step.timestamp or datetime.now(timezone.utc)).isoformat(),
        action = action.type.value if action else "noop",
        target = (action.target if action else "") or "",
        value = (action.value if action and action.value else "") or "",
        reasoning = (action.reasoning if action else "") or "",
        model = (action.model_used if action else "") or "",
        tier = action.tier if action else 0,
        cost_usd = action.cost_usd if action else 0.0,
        risk = action.risk.value if action else "safe",
        approval_status = approvalStatus,
        verification_ok = step.verificationOk,
    )
