"""Completion semantics shared by persistence and evaluation."""
from __future__ import annotations

from typing import Any


FAILURE_REASONS = frozenset({
    "",
    "max_steps_reached",
})

FAILURE_REASON_PREFIXES = (
    "action_failed",
    "auth_expired",
    "background_exception",
    "captcha_detected",
    "cost_cap_reached",
    "eval_error",
    "plan_drift_cancelled",
    "preview_timeout",
    "rejected_by_user",
    "replay_failed",
    "replay_fragment_failed",
    "user_cancelled_preview",
    "wallclock_heartbeat",
)


def completionReasonSucceeded(reason: str) -> bool:
    normalized = (reason or "").strip()
    if normalized in FAILURE_REASONS:
        return False
    return not any(normalized.startswith(prefix) for prefix in FAILURE_REASON_PREFIXES)


def agentStateSucceeded(state: Any) -> bool:
    return bool(
        getattr(state, "isComplete", False)
        and completionReasonSucceeded(str(getattr(state, "completionReason", "")))
    )
