"""Per-channel exponential decay for ACE bullets.

Three independent rates encode the observation that knowledge of different
kinds fades at different speeds. Procedural workflows (`how to do X`) decay
near-zero because they remain valid until the underlying interface changes.
Episodic memories (`user did Y last Tuesday`) decay fastest because they are
inherently time-bound. Semantic facts sit in the middle.
"""

from __future__ import annotations

import math
from typing import Any

SEMANTIC_DECAY_RATE = 0.01
EPISODIC_DECAY_RATE = 0.05
# Phase 12 memory hygiene: bumped from 0.002 to 0.005 so bad procedural
# bullets fade before they pollute a long-lived user's retrieval while
# remaining strictly the slowest of the three channels, matching the
# intent of the ACE reference and the ordering invariant asserted by
# test_decayConstantsOrderedCorrectly.
PROCEDURAL_DECAY_RATE = 0.005


def decayedStrength(strength: float, accessDelta: int, rate: float) -> float:
    return strength * math.exp(-rate * max(accessDelta, 0))


def channelDecayedStrength(bullet: Any, channel: str, currentClock: int) -> float:
    if channel == "semantic":
        return decayedStrength(
            bullet.semantic_strength,
            currentClock - bullet.semantic_access_index,
            SEMANTIC_DECAY_RATE,
        )
    if channel == "episodic":
        return decayedStrength(
            bullet.episodic_strength,
            currentClock - bullet.episodic_access_index,
            EPISODIC_DECAY_RATE,
        )
    if channel == "procedural":
        return decayedStrength(
            bullet.procedural_strength,
            currentClock - bullet.procedural_access_index,
            PROCEDURAL_DECAY_RATE,
        )
    raise ValueError(f"unknown channel {channel!r}")


def totalDecayedStrength(bullet: Any, currentClock: int) -> float:
    return (
        channelDecayedStrength(bullet, "semantic", currentClock)
        + channelDecayedStrength(bullet, "episodic", currentClock)
        + channelDecayedStrength(bullet, "procedural", currentClock)
    )


def dominantChannel(bullet: Any, currentClock: int) -> str:
    contributions = {
        "semantic": channelDecayedStrength(bullet, "semantic", currentClock),
        "episodic": channelDecayedStrength(bullet, "episodic", currentClock),
        "procedural": channelDecayedStrength(bullet, "procedural", currentClock),
    }
    return max(contributions, key=lambda channel: contributions[channel])
