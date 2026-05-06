"""Neo4j-backed framework account and preference persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.persistence.neo4j_client import run_query, run_single

DEFAULT_PREFERENCE = {
    "theme": "aurora",
    "dashboard_window_days": 14,
    "redact_audit_screenshots": True,
}


def _nowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsertGoogleUser(
    *,
    googleSub: str,
    email: str,
    name: str = "",
    picture: str = "",
) -> dict[str, Any]:
    if not googleSub:
        raise RuntimeError("Google userinfo response did not include a subject identifier.")
    userId = f"google:{googleSub}"
    username = name or email.split("@", 1)[0] or userId
    row = run_single(
        """
        MERGE (u:User {id: $id})
        SET u.google_sub = $google_sub,
            u.email = $email,
            u.username = $username,
            u.name = $name,
            u.picture = $picture,
            u.is_active = true,
            u.is_staff = coalesce(u.is_staff, false),
            u.created_at = coalesce(u.created_at, $now),
            u.updated_at = $now
        RETURN u {.*} AS user
        """,
        id=userId,
        google_sub=googleSub,
        email=email,
        username=username,
        name=name,
        picture=picture,
        now=_nowIso(),
    )
    if row is None:
        raise RuntimeError("Failed to persist Google user in Neo4j.")
    return dict(row["user"])


def getUser(userId: str) -> dict[str, Any] | None:
    row = run_single(
        """
        MATCH (u:User {id: $id})
        RETURN u {.*} AS user
        """,
        id=str(userId),
    )
    return dict(row["user"]) if row else None


def preferenceForUser(userId: str) -> dict[str, Any]:
    row = run_single(
        """
        MATCH (u:User {id: $user_id})
        OPTIONAL MATCH (u)-[:HAS_PREFERENCE]->(p:UserPreference {user_id: $user_id})
        RETURN p {.*} AS preference
        """,
        user_id=str(userId),
    )
    if row is None or row.get("preference") is None:
        return dict(DEFAULT_PREFERENCE)
    return _coercePreference(dict(row["preference"]))


def savePreference(
    *,
    userId: str,
    theme: str,
    dashboardWindowDays: int,
    shouldRedactAuditScreenshots: bool,
) -> dict[str, Any]:
    row = run_single(
        """
        MERGE (u:User {id: $user_id})
        MERGE (u)-[:HAS_PREFERENCE]->(p:UserPreference {user_id: $user_id})
        SET p.theme = $theme,
            p.dashboard_window_days = $dashboard_window_days,
            p.redact_audit_screenshots = $redact_audit_screenshots,
            p.created_at = coalesce(p.created_at, $now),
            p.updated_at = $now
        RETURN p {.*} AS preference
        """,
        user_id=str(userId),
        theme=theme,
        dashboard_window_days=int(dashboardWindowDays),
        redact_audit_screenshots=bool(shouldRedactAuditScreenshots),
        now=_nowIso(),
    )
    if row is None:
        raise RuntimeError("Failed to persist user preference in Neo4j.")
    return _coercePreference(dict(row["preference"]))


def ensureUser(userId: str, *, email: str = "", username: str = "") -> None:
    run_query(
        """
        MERGE (u:User {id: $id})
        SET u.email = CASE WHEN $email = "" THEN coalesce(u.email, "") ELSE $email END,
            u.username = CASE WHEN $username = "" THEN coalesce(u.username, $id) ELSE $username END,
            u.is_active = coalesce(u.is_active, true),
            u.is_staff = coalesce(u.is_staff, false),
            u.created_at = coalesce(u.created_at, $now),
            u.updated_at = $now
        """,
        id=str(userId),
        email=email,
        username=username,
        now=_nowIso(),
    )


def _coercePreference(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_PREFERENCE)
    out.update(raw)
    out["dashboard_window_days"] = int(out.get("dashboard_window_days") or 14)
    out["redact_audit_screenshots"] = bool(out.get("redact_audit_screenshots"))
    return out
