"""Phase 1 tests for CUTIEE_CU_BACKEND validation.

`Config.fromEnv()` is the single entry point for backend selection.
Valid values are `gemini` (default) and `browser_use`. Anything else
raises consistent with the no-silent-fallback policy at
`agent/harness/config.py:28`.
"""
from __future__ import annotations

import pytest

from agent.harness.config import ALLOWED_CU_BACKENDS, Config


def test_default_backend_is_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("CUTIEE_CU_BACKEND", raising = False)
    config = Config.fromEnv()
    assert config.cuBackend == "gemini"


def test_browser_use_backend_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("CUTIEE_CU_BACKEND", "browser_use")
    config = Config.fromEnv()
    assert config.cuBackend == "browser_use"


def test_unknown_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("CUTIEE_CU_BACKEND", "not-a-real-backend")
    with pytest.raises(RuntimeError, match = "CUTIEE_CU_BACKEND"):
        Config.fromEnv()


def test_browser_use_requires_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("CUTIEE_CU_BACKEND", "browser_use")
    monkeypatch.delenv("GEMINI_API_KEY", raising = False)
    with pytest.raises(RuntimeError, match = "GEMINI_API_KEY"):
        Config.fromEnv()


def test_allowed_values_are_exactly_two() -> None:
    assert ALLOWED_CU_BACKENDS == frozenset({"gemini", "browser_use"})
