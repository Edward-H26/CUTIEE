"""Cypher-backed audit log repository.

Reads are paginated for the dashboard view; writes are append-only and
called from `agent.safety.audit.buildAuditPayload`.
"""

from __future__ import annotations

from typing import Any

from agent.persistence.neo4j_client import run_query, run_single
from agent.safety.audit import AuditPayload


class AuditEntryRow(dict[str, Any]):
    """Linkable audit-entry row for template rendering.

    Audit entries currently render inside a paginated list view rather than a
    dedicated detail page, so the absolute URL targets the audit dashboard and
    anchors to the row when it is present on the current page.
    """

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return f"{reverse('audit:list')}#audit-{self['id']}"


def appendAudit(payload: AuditPayload) -> None:
    run_query(
        """
        MERGE (u:User {id: $user_id})
        CREATE (a:AuditEntry {
          id: $id,
          user_id: $user_id,
          task_id: $task_id,
          execution_id: $execution_id,
          step_index: $step_index,
          timestamp: datetime($timestamp),
          action: $action,
          target: $target,
          value: $value,
          reasoning: $reasoning,
          model: $model,
          tier: $tier,
          cost_usd: $cost_usd,
          risk: $risk,
          approval_status: $approval_status,
          verification_ok: $verification_ok
        })
        MERGE (u)-[:RECEIVED]->(a)
        """,
        **payload.asDict(),
    )


def listAuditForUser(userId: str, limit: int = 50, offset: int = 0) -> list[AuditEntryRow]:
    rows = run_query(
        """
        MATCH (u:User {id: $user_id})-[:RECEIVED]->(a:AuditEntry)
        RETURN a.id AS id,
               toString(a.timestamp) AS timestamp,
               a.action AS action,
               a.target AS target,
               a.model AS model,
               a.tier AS tier,
               a.cost_usd AS cost_usd,
               a.risk AS risk,
               a.approval_status AS approval_status,
               a.verification_ok AS verification_ok,
               a.task_id AS task_id,
               a.execution_id AS execution_id
        ORDER BY a.timestamp DESC
        SKIP $offset
        LIMIT $limit
        """,
        user_id=str(userId),
        limit=int(limit),
        offset=int(offset),
    )
    return [AuditEntryRow(row) for row in rows]


def auditCountForUser(userId: str) -> int:
    row = run_single(
        """
        MATCH (u:User {id: $user_id})-[:RECEIVED]->(a:AuditEntry)
        RETURN count(a) AS n
        """,
        user_id=str(userId),
    )
    return int(row["n"]) if row else 0


# Backwards-compatible alias used by the existing view layer
list_audit_for_user = listAuditForUser
