"""Template context processors for Neo4j framework auth."""

from __future__ import annotations

from typing import Any

from apps.accounts.neo4j_auth import AnonymousNeo4jUser


def auth(request: Any) -> dict[str, Any]:
    return {"user": getattr(request, "user", AnonymousNeo4jUser())}
