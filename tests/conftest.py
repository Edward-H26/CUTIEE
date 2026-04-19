"""Shared pytest fixtures.

The fast suite never touches Neo4j or llama-server, so most fixtures
inject deterministic stubs. Live-environment tests are marked with
`@pytest.mark.local` (requires Neo4j + llama-server) or
`@pytest.mark.production` (requires Gemini key) and are excluded from
default `pytest` runs via the markers in `pyproject.toml`.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse = True)
def _baseEnv(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set the minimum env required for `cutiee_site.settings` to import."""
    monkeypatch.setenv("CUTIEE_ENV", os.environ.get("CUTIEE_ENV", "local"))
    monkeypatch.setenv("QWEN_SERVER_URL", os.environ.get("QWEN_SERVER_URL", "http://localhost:8001"))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("NEO4J_BOLT_URL", os.environ.get("NEO4J_BOLT_URL", "bolt://localhost:7687"))
    monkeypatch.setenv("NEO4J_USERNAME", os.environ.get("NEO4J_USERNAME", "neo4j"))
    monkeypatch.setenv("NEO4J_PASSWORD", os.environ.get("NEO4J_PASSWORD", "password"))
    monkeypatch.setenv(
        "DJANGO_INTERNAL_DB_URL",
        os.environ.get("DJANGO_INTERNAL_DB_URL", "sqlite:///data/django_internals.sqlite3"),
    )
    yield
