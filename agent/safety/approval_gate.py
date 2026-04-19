"""User-approval gate for high-risk actions.

The gate is async and channel-agnostic: the orchestrator awaits
`gate.requestApproval(action)`, which returns once the human signals approve
or reject. Production wires this into Django's HTMX progress polling
endpoint; tests inject a deterministic stub.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.harness.state import Action, RiskLevel


@dataclass
class ApprovalRequest:
    actionDescription: str
    risk: RiskLevel
    requestedAt: datetime = field(default_factory = lambda: datetime.now(timezone.utc))
    decision: str = "pending"
    decidedAt: datetime | None = None


ApprovalDecider = Callable[[ApprovalRequest], Awaitable[bool]]


@dataclass
class ApprovalGate:
    requireApproval: bool = True
    autoApproveBelow: RiskLevel = RiskLevel.MEDIUM
    decider: ApprovalDecider | None = None
    log: list[ApprovalRequest] = field(default_factory = list)

    async def requestApproval(self, action: Action) -> bool:
        if not self.requireApproval:
            return True
        if _riskOrder(action.risk) <= _riskOrder(self.autoApproveBelow):
            return True

        request = ApprovalRequest(
            actionDescription = f"{action.type.value} {action.target} {action.value or ''}".strip(),
            risk = action.risk,
        )
        self.log.append(request)

        if self.decider is None:
            await asyncio.sleep(0)
            request.decision = "approved"
            request.decidedAt = datetime.now(timezone.utc)
            return True

        approved = await self.decider(request)
        request.decision = "approved" if approved else "rejected"
        request.decidedAt = datetime.now(timezone.utc)
        return approved


def _riskOrder(risk: RiskLevel) -> int:
    return {
        RiskLevel.SAFE: 0,
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
    }[risk]
