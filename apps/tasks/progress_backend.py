"""Pluggable progress backend.

Local mode (and most tests) use the in-memory backend, which works fine
for a single Gunicorn worker. Production with multiple Gunicorn workers
needs a shared store so live HTMX polls land on the same payload no
matter which worker handled the agent run.

Backends:
    CUTIEE_PROGRESS_BACKEND=memory  → in-process dict (default; tests, single worker)
    CUTIEE_PROGRESS_BACKEND=redis   → Redis hash, requires REDIS_URL
    CUTIEE_PROGRESS_BACKEND=neo4j   → Aura-backed `:ProgressSnapshot` nodes
                                       (uses the database we already pay for;
                                       sized for the 2-5 concurrent demo users)

The Neo4j backend trades ~30 ms per publish for free hosting on AuraDB.
A lazy sweep on every publish drops snapshots older than `NEO4J_TTL_SECONDS`
so the graph never grows unbounded; finished snapshots are removed by the
post-finish purge so HTMX pollers stop hammering the DB once the run ends.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

REDIS_KEY_PREFIX = "cutiee:progress:"
REDIS_TTL_SECONDS = 60 * 60 * 24
NEO4J_TTL_SECONDS = 300


class _MemoryBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] = {}

    def publish(self, executionId: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._cache[executionId] = payload

    def fetch(self, executionId: str) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self._cache.get(executionId)
            return dict(snapshot) if snapshot else None


class _RedisBackend:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)

    def publish(self, executionId: str, payload: dict[str, Any]) -> None:
        self._client.set(
            REDIS_KEY_PREFIX + executionId,
            json.dumps(payload, default=str),
            ex=REDIS_TTL_SECONDS,
        )

    def fetch(self, executionId: str) -> dict[str, Any] | None:
        raw = self._client.get(REDIS_KEY_PREFIX + executionId)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None


class _Neo4jBackend:
    """Aura-backed progress for the demo deployment.

    Stores one `:ProgressSnapshot {execution_id}` node per active run. Every
    publish lazily sweeps stale snapshots so we don't need a cron. When a
    run reports `finished=True`, the node is dropped after the next poll so
    HTMX stops querying. Sized for 2-5 concurrent demo users; not for
    high-concurrency production traffic.
    """

    DEFAULT_TTL_SECONDS = NEO4J_TTL_SECONDS

    def __init__(self) -> None:
        from agent.persistence.neo4j_client import run_query

        self._run = run_query

    def publish(self, executionId: str, payload: dict[str, Any]) -> None:
        self._run(
            """
            MERGE (p:ProgressSnapshot {execution_id: $eid})
            SET p.payload = $payload,
                p.updated_at = datetime(),
                p.finished = $finished
            """,
            eid=executionId,
            payload=json.dumps(payload, default=str),
            finished=bool(payload.get("finished")),
        )
        # Lazy sweep: drop snapshots older than TTL. Cheap when the table is small.
        self._run(
            """
            MATCH (p:ProgressSnapshot)
            WHERE p.updated_at < datetime() - duration({seconds: $ttl})
            DETACH DELETE p
            """,
            ttl=self.DEFAULT_TTL_SECONDS,
        )

    def fetch(self, executionId: str) -> dict[str, Any] | None:
        rows = self._run(
            """
            MATCH (p:ProgressSnapshot {execution_id: $eid})
            RETURN p.payload AS payload, p.finished AS finished
            """,
            eid=executionId,
        )
        if not rows:
            return None
        try:
            payload = json.loads(rows[0]["payload"])
        except (TypeError, ValueError):
            return None
        if rows[0].get("finished"):
            # Demo cleanup: once the client has seen the finished payload,
            # drop the node so subsequent polls hit the DB-backed fallback path.
            self._run(
                "MATCH (p:ProgressSnapshot {execution_id: $eid}) DETACH DELETE p",
                eid=executionId,
            )
        return payload


Backend = _MemoryBackend | _RedisBackend | _Neo4jBackend
_BACKEND: Backend | None = None
_BACKEND_LOCK = threading.Lock()


def getBackend() -> Backend:
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    with _BACKEND_LOCK:
        if _BACKEND is None:
            kind = (os.environ.get("CUTIEE_PROGRESS_BACKEND") or "memory").lower()
            if kind == "redis":
                redisUrl = os.environ.get("REDIS_URL")
                if not redisUrl:
                    raise RuntimeError(
                        "CUTIEE_PROGRESS_BACKEND=redis requires REDIS_URL. "
                        "On Render, wire it via fromService."
                    )
                _BACKEND = _RedisBackend(redisUrl)
            elif kind == "neo4j":
                _BACKEND = _Neo4jBackend()
            else:
                _BACKEND = _MemoryBackend()
    return _BACKEND


def resetBackendForTests() -> None:
    """Test-only helper to clear the cached singleton."""
    global _BACKEND
    with _BACKEND_LOCK:
        _BACKEND = None


def publishProgress(executionId: str, payload: dict[str, Any]) -> None:
    getBackend().publish(executionId, payload)


def fetchProgress(executionId: str) -> dict[str, Any] | None:
    return getBackend().fetch(executionId)
