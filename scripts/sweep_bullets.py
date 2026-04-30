"""Nightly decay-to-zero sweeper.

Iterates every user's bullet store, recomputes the total decayed
strength for each bullet, and removes the ones that have fallen to
`DECAY_FLOOR` or below. Invoked from cron or any scheduler.

Usage:
    python -m scripts.sweep_bullets
"""

from __future__ import annotations

import logging
import sys

from agent.memory.ace_memory import ACEMemory
from agent.persistence.neo4j_client import run_query

DECAY_FLOOR = 0.01

logger = logging.getLogger("cutiee.sweep_bullets")


def iterUserIds() -> list[str]:
    rows = run_query("MATCH (u:User) RETURN u.id AS id")
    return [row["id"] for row in rows if row.get("id")]


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    userIds = iterUserIds()
    totalRemoved = 0
    for userId in userIds:
        try:
            from apps.memory_app.store import Neo4jBulletStore

            memory = ACEMemory(userId=userId, store=Neo4jBulletStore())
            memory.loadFromStore()
            removed = memory.sweepDecayedBullets(floor=DECAY_FLOOR)
            totalRemoved += removed
            if removed:
                logger.info("user=%s removed=%d", userId, removed)
        except Exception as exc:  # noqa: BLE001 - one user's failure must not stop the sweep
            logger.warning("sweep failed for user=%s: %r", userId, exc)
    logger.info("sweep complete: users=%d removed=%d", len(userIds), totalRemoved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
