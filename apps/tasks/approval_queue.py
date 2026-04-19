"""In-process approval queue for high-risk actions.

The orchestrator's `ApprovalGate` is async by design. Hooking it up to a
real UI means: when a high-risk action shows up, push the request into
this queue, then await on it. The HTMX detail page polls
`pendingApprovalFor(executionId)`, renders a modal, and POSTs the user's
decision through `submitDecision()`, which releases the agent loop.

Threading model:
- The agent runs in a `threading.Thread` (spawned in api.py) with its own
  `asyncio.run()` loop.
- HTTP requests (including the approval POST) are handled on Django's
  request thread, which is a different thread with no event loop of its
  own.
- An `asyncio.Event` is loop-bound; `event.set()` from another thread
  works on CPython by accident but doesn't wake the awaiter reliably.
- Therefore: we capture the agent loop reference at park time and use
  `loop.call_soon_threadsafe(event.set)` to release it cross-thread.

This is the **demo-scoped** implementation: it uses a process-local dict.
For multi-worker production you'd swap in a Neo4j-backed pending queue
(same shape as `_Neo4jBackend` in progress_backend.py). 2-5 concurrent
demo users on a single Gunicorn worker is well within scope.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent.harness.state import RiskLevel
from agent.safety.approval_gate import ApprovalRequest


@dataclass
class PendingDecision:
    request: ApprovalRequest
    event: asyncio.Event
    loop: Any  # asyncio.AbstractEventLoop - typed loosely to avoid cross-version issues
    decision: bool | None = None
    createdAt: datetime = field(default_factory = lambda: datetime.now(timezone.utc))


_PENDING: dict[str, PendingDecision] = {}
_LOCK = threading.Lock()


async def awaitDecision(executionId: str, request: ApprovalRequest) -> bool:
    """Park the agent until the user posts approve/reject for this execution.

    Captures the running loop so `submitDecision()` can wake us
    safely from the Django request thread.
    """
    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    pending = PendingDecision(request = request, event = event, loop = loop)
    with _LOCK:
        _PENDING[executionId] = pending
    try:
        await event.wait()
        return bool(pending.decision)
    finally:
        with _LOCK:
            _PENDING.pop(executionId, None)


def pendingApprovalFor(executionId: str) -> dict | None:
    with _LOCK:
        pending = _PENDING.get(executionId)
    if pending is None:
        return None
    return {
        "actionDescription": pending.request.actionDescription,
        "risk": pending.request.risk.value,
        "createdAt": pending.createdAt.isoformat(),
    }


def submitDecision(executionId: str, approved: bool) -> bool:
    """Resolve the pending decision; returns True if a request was waiting.

    Uses the captured loop's `call_soon_threadsafe` to flip the event so
    the cross-thread wakeup is reliable on every Python implementation.
    """
    with _LOCK:
        pending = _PENDING.get(executionId)
    if pending is None:
        return False
    pending.decision = approved
    pending.loop.call_soon_threadsafe(pending.event.set)
    return True


def buildExecutionGate(executionId: str) -> "_ExecutionScopedGate":
    """Wire the in-process queue to ApprovalGate.decider for one execution."""
    return _ExecutionScopedGate(executionId = executionId)


@dataclass
class _ExecutionScopedGate:
    executionId: str

    async def __call__(self, request: ApprovalRequest) -> bool:
        # High-risk only; the gate already auto-approves below MEDIUM.
        if request.risk == RiskLevel.SAFE:
            return True
        return await awaitDecision(self.executionId, request)
