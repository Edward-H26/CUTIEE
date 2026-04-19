"""Pluggable progress backend.

Local mode (and most tests) use the in-memory backend, which works fine
for a single Gunicorn worker. Production on Render runs Gunicorn with
multiple workers, so live HTMX progress polls might land on a different
worker than the one running the agent. The Redis backend solves that by
publishing the per-execution snapshot to a shared Redis hash.

Selection:
    CUTIEE_PROGRESS_BACKEND=memory  → in-process dict (default)
    CUTIEE_PROGRESS_BACKEND=redis   → Redis hash, requires REDIS_URL
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

REDIS_KEY_PREFIX = "cutiee:progress:"
REDIS_TTL_SECONDS = 60 * 60 * 24


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
        import redis  # local import: only required in production

        self._client = redis.Redis.from_url(url, decode_responses = True)

    def publish(self, executionId: str, payload: dict[str, Any]) -> None:
        self._client.set(
            REDIS_KEY_PREFIX + executionId,
            json.dumps(payload, default = str),
            ex = REDIS_TTL_SECONDS,
        )

    def fetch(self, executionId: str) -> dict[str, Any] | None:
        raw = self._client.get(REDIS_KEY_PREFIX + executionId)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None


_BACKEND: _MemoryBackend | _RedisBackend | None = None
_BACKEND_LOCK = threading.Lock()


def getBackend() -> _MemoryBackend | _RedisBackend:
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
            else:
                _BACKEND = _MemoryBackend()
    return _BACKEND


def publishProgress(executionId: str, payload: dict[str, Any]) -> None:
    getBackend().publish(executionId, payload)


def fetchProgress(executionId: str) -> dict[str, Any] | None:
    return getBackend().fetch(executionId)
