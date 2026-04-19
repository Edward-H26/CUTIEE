"""Cypher-backed CRUD for `:Session` nodes (Django session storage)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .neo4j_client import run_query, run_single


def load_django_session(session_key: str) -> dict[str, Any] | None:
    return run_single(
        """
        MATCH (s:Session {session_key: $key})
        RETURN s.data AS data, s.expire AS expire
        """,
        key = session_key,
    )


def django_session_exists(session_key: str) -> bool:
    row = run_single(
        "MATCH (s:Session {session_key: $key}) RETURN count(s) AS n",
        key = session_key,
    )
    return bool(row and row["n"] > 0)


def save_django_session(session_key: str, data: str, expire: str) -> None:
    run_query(
        """
        MERGE (s:Session {session_key: $key})
        SET s.data = $data, s.expire = $expire
        """,
        key = session_key,
        data = data,
        expire = expire,
    )


def delete_django_session(session_key: str) -> None:
    run_query(
        "MATCH (s:Session {session_key: $key}) DETACH DELETE s",
        key = session_key,
    )


def cleanup_expired_sessions() -> int:
    now = datetime.now(timezone.utc).isoformat()
    row = run_single(
        """
        MATCH (s:Session)
        WHERE s.expire IS NOT NULL AND s.expire < $now
        DETACH DELETE s
        RETURN count(s) AS removed
        """,
        now = now,
    )
    return int(row["removed"]) if row else 0
