"""Cross-thread approval queue test.

Guards the regression where `submitDecision` from the Django request
thread doesn't wake the agent thread because `asyncio.Event.set()` is
not loop-safe across threads. The fix uses
`loop.call_soon_threadsafe(event.set)`; this test would hang (timeout)
if anyone reverts that fix.
"""

from __future__ import annotations

import asyncio
import threading
import time

from agent.harness.state import RiskLevel
from agent.safety.approval_gate import ApprovalRequest
from apps.tasks.approval_queue import awaitDecision, submitDecision


def test_cross_thread_wakeup() -> None:
    box: dict[str, bool] = {}

    async def park() -> None:
        request = ApprovalRequest(
            actionDescription="delete account",
            risk=RiskLevel.HIGH,
        )
        decision = await awaitDecision("ex-cross-thread-1", request)
        box["decision"] = decision

    def runAgentLoop() -> None:
        asyncio.run(park())

    t = threading.Thread(target=runAgentLoop, daemon=True)
    t.start()
    # Give the agent loop a beat to register the pending decision.
    time.sleep(0.05)

    delivered = submitDecision("ex-cross-thread-1", True)
    assert delivered is True

    t.join(timeout=2.0)
    assert not t.is_alive(), "agent thread should have exited cleanly"
    assert box.get("decision") is True


def test_decline_propagates() -> None:
    box: dict[str, bool] = {}

    async def park() -> None:
        request = ApprovalRequest(
            actionDescription="delete account",
            risk=RiskLevel.HIGH,
        )
        box["decision"] = await awaitDecision("ex-cross-thread-2", request)

    t = threading.Thread(target=lambda: asyncio.run(park()), daemon=True)
    t.start()
    time.sleep(0.05)
    submitDecision("ex-cross-thread-2", False)
    t.join(timeout=2.0)
    assert box.get("decision") is False


def test_submit_with_no_pending_returns_false() -> None:
    assert submitDecision("not-pending", True) is False
