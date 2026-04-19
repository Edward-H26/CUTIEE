"""Unit tests for the pluggable progress backend."""
from __future__ import annotations

import importlib

import pytest


def _reloadBackend():
    from apps.tasks import progress_backend

    progress_backend._BACKEND = None
    importlib.reload(progress_backend)
    return progress_backend


def test_memoryBackendDefault(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CUTIEE_PROGRESS_BACKEND", raising = False)
    pb = _reloadBackend()
    pb.publishProgress("exec-1", {"step": 1})
    assert pb.fetchProgress("exec-1") == {"step": 1}
    assert pb.fetchProgress("missing") is None


def test_memoryBackendKeysIsolatePerExecution(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CUTIEE_PROGRESS_BACKEND", raising = False)
    pb = _reloadBackend()
    pb.publishProgress("a", {"v": 1})
    pb.publishProgress("b", {"v": 2})
    assert pb.fetchProgress("a") == {"v": 1}
    assert pb.fetchProgress("b") == {"v": 2}


def test_redisBackendRequiresUrl(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CUTIEE_PROGRESS_BACKEND", "redis")
    monkeypatch.delenv("REDIS_URL", raising = False)
    pb = _reloadBackend()
    with pytest.raises(RuntimeError, match = "REDIS_URL"):
        pb.getBackend()
