"""Phase 4 Neo4j-backed cost ledger for wallet cap enforcement.

Every step writes its projected USD cost into a Neo4j `:CostLedger`
node keyed on `(user_id, hour_key)` where `hour_key` is
`YYYY-MM-DD-HH`. A breach of either the per-task or per-hour cap ends
the run cleanly with `completionReason="cost_cap_reached"`.

The ledger uses `MERGE` so the increment is atomic under concurrent
access, and a nightly job prunes ledger rows older than 48 hours so
the table never grows unbounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from agent.persistence.metrics import recordCost
from agent.persistence.neo4j_client import run_single


@dataclass
class LedgerDecision:
    exceeded: bool
    hourlyUsd: float = 0.0
    reason: str = ""


def hourKey(now: datetime | None = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    return stamp.strftime("%Y-%m-%d-%H")


def dayKey(now: datetime | None = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    return stamp.strftime("%Y-%m-%d")


def incrementAndCheck(
    *,
    userId: str,
    deltaUsd: float,
    maxPerHour: float,
    maxPerDay: float = 0.0,
    now: datetime | None = None,
) -> LedgerDecision:
    """Atomically add `deltaUsd` to the user's current-hour ledger and
    check both the per-hour and per-day aggregates.

    Per-day tracking sums the hourly rows for the current UTC date in
    the same Cypher statement so a single roundtrip gates both caps.
    """
    stamp = now or datetime.now(timezone.utc)
    record = run_single(
        """
        MERGE (l:CostLedger {user_id: $userId, hour_key: $hourKey})
          ON CREATE SET l.hourly_usd = $delta,
                        l.day_key = $dayKey,
                        l.created_at = datetime()
          ON MATCH  SET l.hourly_usd = l.hourly_usd + $delta,
                        l.day_key = coalesce(l.day_key, $dayKey),
                        l.updated_at = datetime()
        WITH l
        MATCH (d:CostLedger {user_id: $userId, day_key: $dayKey})
        RETURN l.hourly_usd AS hourly,
               sum(d.hourly_usd) AS daily
        """,
        userId=userId,
        hourKey=hourKey(stamp),
        dayKey=dayKey(stamp),
        delta=float(deltaUsd),
    )
    hourly = float(record["hourly"]) if record and "hourly" in record else deltaUsd
    daily = float(record["daily"]) if record and "daily" in record else hourly
    recordCost(scope="per_hour", deltaUsd=float(deltaUsd))
    if maxPerDay > 0 and daily > maxPerDay:
        return LedgerDecision(
            exceeded=True,
            hourlyUsd=hourly,
            reason="per_day_cap_reached",
        )
    if hourly > maxPerHour:
        return LedgerDecision(
            exceeded=True,
            hourlyUsd=hourly,
            reason="per_hour_cap_reached",
        )
    return LedgerDecision(exceeded=False, hourlyUsd=hourly)


def wouldExceed(
    *,
    userId: str,
    projectedDeltaUsd: float,
    maxPerHour: float,
    maxPerDay: float = 0.0,
    now: datetime | None = None,
) -> LedgerDecision:
    stamp = now or datetime.now(timezone.utc)
    record = run_single(
        """
        OPTIONAL MATCH (h:CostLedger {user_id: $userId, hour_key: $hourKey})
        WITH coalesce(h.hourly_usd, 0.0) AS hourly
        OPTIONAL MATCH (d:CostLedger {user_id: $userId, day_key: $dayKey})
        RETURN hourly AS hourly,
               coalesce(sum(d.hourly_usd), 0.0) AS daily
        """,
        userId=userId,
        hourKey=hourKey(stamp),
        dayKey=dayKey(stamp),
    )
    currentHourly = float(record["hourly"]) if record and "hourly" in record else 0.0
    currentDaily = float(record["daily"]) if record and "daily" in record else 0.0
    delta = max(0.0, float(projectedDeltaUsd))
    if maxPerDay > 0 and currentDaily + delta > maxPerDay:
        return LedgerDecision(
            exceeded=True,
            hourlyUsd=currentHourly,
            reason="per_day",
        )
    if maxPerHour > 0 and currentHourly + delta > maxPerHour:
        return LedgerDecision(
            exceeded=True,
            hourlyUsd=currentHourly,
            reason="per_hour",
        )
    return LedgerDecision(exceeded=False, hourlyUsd=currentHourly)


def pruneOldLedgers(hoursBack: int = 48) -> int:
    """Delete :CostLedger nodes older than `hoursBack`.

    Intended for a nightly job. Returns the number of deletions so the
    job can log activity.
    """
    record = run_single(
        """
        MATCH (l:CostLedger)
        WHERE datetime() - duration({hours: $hours}) > coalesce(l.updated_at, l.created_at)
        WITH l LIMIT 10000
        DETACH DELETE l
        RETURN count(l) AS removed
        """,
        hours=int(hoursBack),
    )
    return int(record["removed"]) if record and "removed" in record else 0
