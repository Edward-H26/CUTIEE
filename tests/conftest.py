"""Shared pytest fixtures.

The fast suite never touches the live Gemini API. Live-environment
tests are marked with `@pytest.mark.local` (requires a reachable
Neo4j bolt endpoint; uses `MockComputerUseClient`) or
`@pytest.mark.production` (requires `GEMINI_API_KEY` and Chromium)
and are excluded from default `pytest` runs via the markers in
`pyproject.toml`.

Two defenses are wired up here so the fast suite runs cleanly
regardless of the developer's `.env`:

1. **Module-level env block** forces test-safe defaults into
   `os.environ` at conftest import time. This wins most ordering
   races but cannot beat `pytest-django`'s early plugin
   initialization, which imports `cutiee_site.settings` before any
   conftest file is loaded.
2. **`_disableHttpsRedirectInTests` autouse fixture** uses
   pytest-django's `settings` fixture to override
   `SECURE_SSL_REDIRECT` and `SECURE_HSTS_SECONDS` per-test. Without
   this, a `.env` that carries `CUTIEE_ENV=production` triggers the
   production hardening branch in `cutiee_site/settings.py`, and the
   test client returns 301 for every plain-HTTP request.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


_TEST_ENV_DEFAULTS: dict[str, str] = {
    "CUTIEE_ENV": "local",
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "NEO4J_BOLT_URL": "bolt://localhost:7687",
    "NEO4J_USERNAME": "neo4j",
    "NEO4J_PASSWORD": "password",
    "DJANGO_INTERNAL_DB_URL": "sqlite:///:memory:",
}


os.environ["CUTIEE_ENV"] = _TEST_ENV_DEFAULTS["CUTIEE_ENV"]
for _k, _v in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)


@pytest.fixture(autouse = True)
def _baseEnv(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Per-test pin so a stray env mutation cannot leak between tests."""
    monkeypatch.setenv("CUTIEE_ENV", _TEST_ENV_DEFAULTS["CUTIEE_ENV"])
    for key, default in _TEST_ENV_DEFAULTS.items():
        if key == "CUTIEE_ENV":
            continue
        monkeypatch.setenv(key, os.environ.get(key, default))
    yield


@pytest.fixture(autouse = True)
def _disableHttpsRedirectInTests(settings) -> None:
    """Disable production HTTPS-redirect middleware for the fast suite.

    `cutiee_site.settings` reads `.env` at import time and commonly
    sees `CUTIEE_ENV=production` from a developer's local-dev config.
    That flips `SECURE_SSL_REDIRECT=True`, and Django's test client
    then returns 301 for every plain-HTTP request instead of the real
    200/302/... response the tests expect. pytest-django's `settings`
    fixture overrides Django settings per-test and restores them on
    teardown, which is the right granularity for this test-only
    override.
    """
    settings.SECURE_SSL_REDIRECT = False
    settings.SECURE_HSTS_SECONDS = 0
