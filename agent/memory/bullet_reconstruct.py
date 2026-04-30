"""Canonical reconstruction of an `Action` from procedural bullet content.

Pre-2026-04-22 both `replay.py:_actionFromBullet` and
`fragment_replay.py:_fragmentActionFromBullet` carried ~60 near-duplicate
lines. They diverged only in value handling: whole-plan replay keeps the
stored value verbatim (pure zero-cost replay), while fragment replay flags
bullets with populated values for the model loop to supply a fresh value.

This module holds the single canonical implementation. Callers set
`modelVariantOnNonEmptyValue` to opt into fragment semantics; whole-plan
replay ignores the second tuple element and uses the stored value as-is.
"""

from __future__ import annotations

import re

from ..harness.state import Action, ActionType, RiskLevel
from .bullet import Bullet

_ACTION_PATTERN = re.compile(r"action=(\w+)")
_TARGET_PATTERN_SINGLE = re.compile(r"target='([^']*)'")
_TARGET_PATTERN_DOUBLE = re.compile(r'target="([^"]*)"')
_VALUE_PATTERN_SINGLE = re.compile(r"value='([^']*)'")
_VALUE_PATTERN_DOUBLE = re.compile(r'value="([^"]*)"')
_COORD_PATTERN = re.compile(r"coordinate=\((-?\d+),(-?\d+)\)")
_KEYS_PATTERN = re.compile(r"keys=([\w+,\-]+)")
_SCROLL_PATTERN = re.compile(r"scroll=\((-?\d+),(-?\d+)\)")


def actionFromBullet(
    bullet: Bullet,
    *,
    modelVariantOnNonEmptyValue: bool = False,
    reasoningPrefix: str = "replay",
    modelUsed: str = "replay",
) -> tuple[Action | None, bool]:
    """Reconstruct an `Action` from a procedural bullet.

    Returns `(action, requires_model_value)`. Whole-plan replay callers
    ignore the second element and accept the stored value as-is. Fragment
    replay callers use both: when `modelVariantOnNonEmptyValue=True` and
    the stored `value` field is non-empty (or carries a `<redacted:N>`
    marker from Phase 10), the returned Action emits with `value=None`
    and the flag is `True`, so the runner falls through to the model loop
    for that step while still replaying the coordinate.
    """
    actionMatch = _ACTION_PATTERN.search(bullet.content)
    if actionMatch is None:
        return None, False
    try:
        actionType = ActionType(actionMatch.group(1))
    except ValueError:
        return None, False

    targetMatch = _TARGET_PATTERN_SINGLE.search(bullet.content) or _TARGET_PATTERN_DOUBLE.search(
        bullet.content
    )
    valueMatch = _VALUE_PATTERN_SINGLE.search(bullet.content) or _VALUE_PATTERN_DOUBLE.search(
        bullet.content
    )
    coordMatch = _COORD_PATTERN.search(bullet.content)
    keysMatch = _KEYS_PATTERN.search(bullet.content)
    scrollMatch = _SCROLL_PATTERN.search(bullet.content)

    target = targetMatch.group(1) if targetMatch else ""
    rawValue = valueMatch.group(1) if valueMatch else ""
    coordinate = (int(coordMatch.group(1)), int(coordMatch.group(2))) if coordMatch else None
    keys = keysMatch.group(1).split(",") if keysMatch else None
    scrollDx = int(scrollMatch.group(1)) if scrollMatch else 0
    scrollDy = int(scrollMatch.group(2)) if scrollMatch else 0

    # Phase 10 redaction stores the literal `<redacted:N>` marker in
    # place of the original secret. A replay must never surface that
    # literal string; treat it as value-variant so the model re-derives.
    isRedacted = rawValue.startswith("<redacted:")
    requiresModelValue = modelVariantOnNonEmptyValue and (bool(rawValue) or isRedacted)
    emittedValue: str | None
    if requiresModelValue:
        emittedValue = None
    else:
        emittedValue = rawValue or None

    requiresApproval = "risk:high" in bullet.tags
    risk = RiskLevel.HIGH if requiresApproval else RiskLevel.LOW
    action = Action(
        type=actionType,
        target=target,
        value=emittedValue,
        coordinate=coordinate,
        keys=keys,
        scrollDx=scrollDx,
        scrollDy=scrollDy,
        reasoning=f"{reasoningPrefix}:{bullet.id[:8]}",
        model_used=modelUsed,
        tier=0,
        confidence=1.0,
        risk=risk,
        cost_usd=0.0,
        requires_approval=requiresApproval,
    )
    return action, requiresModelValue
