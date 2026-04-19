"""Unit tests for the pluggable progress backend."""
from __future__ import annotations

import pytest

from apps.tasks import progress_backend


@pytest.fixture(autouse = True)
def _reset_backend():
    progress_backend.resetBackendForTests()
    yield
    progress_backend.resetBackendForTests()


def test_memoryBackendDefault(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CUTIEE_PROGRESS_BACKEND", raising = False)
    progress_backend.publishProgress("exec-1", {"step": 1})
    assert progress_backend.fetchProgress("exec-1") == {"step": 1}
    assert progress_backend.fetchProgress("missing") is None


def test_memoryBackendKeysIsolatePerExecution(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CUTIEE_PROGRESS_BACKEND", raising = False)
    progress_backend.publishProgress("a", {"v": 1})
    progress_backend.publishProgress("b", {"v": 2})
    assert progress_backend.fetchProgress("a") == {"v": 1}
    assert progress_backend.fetchProgress("b") == {"v": 2}


def test_redisBackendRequiresUrl(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CUTIEE_PROGRESS_BACKEND", "redis")
    monkeypatch.delenv("REDIS_URL", raising = False)
    with pytest.raises(RuntimeError, match = "REDIS_URL"):
        progress_backend.getBackend()


def test_neo4jBackendSelectable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CUTIEE_PROGRESS_BACKEND", "neo4j")
    backend = progress_backend.getBackend()
    assert isinstance(backend, progress_backend._Neo4jBackend)


def test_neo4jBackendUsesRunQuery(monkeypatch: pytest.MonkeyPatch):
    """Verify the backend dispatches Cypher via the persistence layer."""
    monkeypatch.setenv("CUTIEE_PROGRESS_BACKEND", "neo4j")

    captured: list[tuple[str, dict]] = []

    def _fake_run_query(cypher: str, **params):
        captured.append((cypher, params))
        if "RETURN p.payload" in cypher:
            import json

            return [{"payload": json.dumps({"step": 7, "finished": False}), "finished": False}]
        return []

    from agent.persistence import neo4j_client

    monkeypatch.setattr(neo4j_client, "run_query", _fake_run_query)

    progress_backend.resetBackendForTests()
    progress_backend.publishProgress("exec-9", {"step": 7, "finished": False})
    snapshot = progress_backend.fetchProgress("exec-9")

    assert snapshot == {"step": 7, "finished": False}
    publishedCypher = captured[0][0]
    assert "MERGE (p:ProgressSnapshot" in publishedCypher
    sweepCypher = captured[1][0]
    assert "DETACH DELETE p" in sweepCypher
