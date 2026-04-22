"""Django-side helpers for the :PreviewApproval Neo4j node.

The preview approval flow splits across two processes:

  1. The agent runtime (`agent/harness/preview.py::runPreviewAndWait`)
     MERGEs the :PreviewApproval node with status='pending' and polls
     it until status flips to 'approved' or 'cancelled'.
  2. The Django request thread (this module) reads that node to render
     the modal, and writes status on user approve/cancel input.

Keeping the Neo4j helpers in apps/tasks/ (rather than agent/) mirrors
the apps/*/repo.py pattern: Cypher that reads/writes user-facing state
lives in apps/, and the agent runtime stays Django-free.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.persistence.neo4j_client import run_query, run_single


def fetchPreviewApproval(executionId: str) -> dict[str, Any] | None:
    """Return the :PreviewApproval node for an execution, or None."""
    row = run_single(
        """
        MATCH (p:PreviewApproval {execution_id: $eid})
        RETURN p {.*} AS preview
        """,
        eid = str(executionId),
    )
    return row["preview"] if row else None


def setPreviewStatus(executionId: str, *, status: str, note: str = "") -> bool:
    """Flip :PreviewApproval.status to approved or cancelled.

    Returns True if a matching node was updated. The runner's poll loop
    sees the flip on its next iteration and exits `runPreviewAndWait`
    with the corresponding PreviewOutcome.
    """
    allowed = {"approved", "cancelled", "pending"}
    if status not in allowed:
        raise ValueError(f"preview status must be one of {sorted(allowed)}, got {status!r}")
    rows = run_query(
        """
        MATCH (p:PreviewApproval {execution_id: $eid})
        SET p.status = $status,
            p.note = $note,
            p.updated_at = $nowIso
        RETURN p.execution_id AS id
        """,
        eid = str(executionId),
        status = status,
        note = note,
        nowIso = datetime.now(timezone.utc).isoformat(),
    )
    return bool(rows)
