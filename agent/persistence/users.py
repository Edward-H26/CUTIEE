"""Cypher-backed CRUD for `:User` nodes.

Only the subset needed by the auth and allauth flows lives here. More complex
user queries (audit joins, task ownership) stay in apps/tasks/repo.py etc.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from django.contrib.auth.hashers import check_password, make_password

from agent.persistence.neo4j_client import run_query, run_single


def create_user(
    username: str,
    email: str,
    password: str,
    *,
    is_active: bool = True,
    is_staff: bool = False,
) -> dict[str, Any]:
    user_id = str(uuid.uuid4())
    password_hash = make_password(password)
    now = datetime.now(timezone.utc).isoformat()
    row = run_single(
        """
        CREATE (u:User {
          id: $id,
          username: $username,
          email: $email,
          password_hash: $password_hash,
          is_active: $is_active,
          is_staff: $is_staff,
          created_at: $created_at,
          last_login: null
        })
        RETURN u {.*} AS user
        """,
        id = user_id,
        username = username,
        email = email,
        password_hash = password_hash,
        is_active = is_active,
        is_staff = is_staff,
        created_at = now,
    )
    if row is None:
        raise RuntimeError(f"Failed to create user {username!r}")
    return row["user"]


def get_user_by_username(username: str) -> dict[str, Any] | None:
    row = run_single(
        "MATCH (u:User {username: $username}) RETURN u {.*} AS user",
        username = username,
    )
    return row["user"] if row else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    row = run_single(
        "MATCH (u:User {email: $email}) RETURN u {.*} AS user",
        email = email,
    )
    return row["user"] if row else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    row = run_single(
        "MATCH (u:User {id: $id}) RETURN u {.*} AS user",
        id = user_id,
    )
    return row["user"] if row else None


def verify_password(user_data: dict[str, Any], password: str) -> bool:
    stored = user_data.get("password_hash", "")
    return bool(stored) and check_password(password, stored)


def update_last_login(user_id: str) -> None:
    run_query(
        "MATCH (u:User {id: $id}) SET u.last_login = $now",
        id = user_id,
        now = datetime.now(timezone.utc).isoformat(),
    )
