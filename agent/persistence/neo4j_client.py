"""Neo4j driver factory and query helpers.

Adapted from miramemoria/app/services/neo4j_memory.py. The CUTIEE deltas:
- Environment variable is NEO4J_BOLT_URL (not NEO4J_URI)
- Missing credentials raise RuntimeError instead of returning None silently
- Unreachable bolt endpoints raise RuntimeError on first use with a remediation hint
"""
from __future__ import annotations

import os
import threading
from typing import Any, cast

from neo4j import Driver, GraphDatabase, Query
from neo4j.exceptions import ServiceUnavailable

_DRIVER: Driver | None = None
_DRIVER_LOCK = threading.Lock()


def _safe_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _safe_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed >= 0.0 else default


_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "NEO4J_BOLT_URL": ("NEO4J_URI",),
}


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        for alias in _ENV_ALIASES.get(name, ()):
            value = os.getenv(alias)
            if value:
                break
    if not value:
        raise RuntimeError(
            f"Neo4j configuration missing: {name}. Start a local Neo4j via "
            "`./scripts/neo4j_up.sh`, or set AuraDB credentials. See .env.example."
        )
    return value


def get_driver() -> Driver:
    """Return a cached Neo4j driver. Raises if config is missing or unreachable."""
    global _DRIVER
    if _DRIVER is not None:
        return _DRIVER

    uri = _required_env("NEO4J_BOLT_URL")
    user = _required_env("NEO4J_USERNAME")
    password = _required_env("NEO4J_PASSWORD")

    with _DRIVER_LOCK:
        if _DRIVER is None:
            _DRIVER = GraphDatabase.driver(
                uri,
                auth = (user, password),
                max_connection_pool_size = _safe_env_int("NEO4J_MAX_CONNECTION_POOL_SIZE", 32),
                connection_timeout = _safe_env_float("NEO4J_CONNECTION_TIMEOUT", 30.0),
                max_transaction_retry_time = _safe_env_float("NEO4J_MAX_TX_RETRY", 15.0),
                keep_alive = True,
            )
    return _DRIVER


def _database() -> str | None:
    return os.getenv("NEO4J_DATABASE") or None


def close_driver() -> None:
    global _DRIVER
    with _DRIVER_LOCK:
        if _DRIVER is not None:
            try:
                _DRIVER.close()
            finally:
                _DRIVER = None


def run_query(cypher: str, **params: Any) -> list[dict[str, Any]]:
    """Run a Cypher query and return all result rows as dicts."""
    driver = get_driver()
    db = _database()
    query = Query(cast("Any", cypher))
    try:
        with driver.session(database = db) as session:
            result = session.run(query, **params)
            return [dict(record) for record in result]
    except ServiceUnavailable as exc:
        raise RuntimeError(
            f"Neo4j unreachable at {os.getenv('NEO4J_BOLT_URL')!r}. "
            "Run `./scripts/neo4j_up.sh` locally, or verify AuraDB credentials "
            "in production."
        ) from exc


def run_single(cypher: str, **params: Any) -> dict[str, Any] | None:
    """Run a Cypher query expected to return at most one row."""
    rows = run_query(cypher, **params)
    if not rows:
        return None
    if len(rows) > 1:
        raise RuntimeError(
            f"run_single expected at most one row, got {len(rows)} for cypher: {cypher[:80]!r}"
        )
    return rows[0]
