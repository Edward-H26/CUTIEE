"""Phase 16 pre-run preview.

Before the runner touches the browser, it surfaces a natural-language
summary of the planned approach and blocks until the user approves or
cancels. The preview lives in Neo4j as a `:PreviewApproval` node keyed
on `executionId`; the HTMX dashboard polls that node and flips its
status on user input.

Callers (typically the Django wiring layer) are responsible for
generating the summary string and passing it in. This module owns the
Neo4j persist-and-poll helper plus the terminal outcome dataclass; it
stays free of CuClient coupling so the agent package remains vendorable.
Cancellation marks the run complete with
`completionReason="user_cancelled_preview"` without touching the browser.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from agent.persistence.neo4j_client import run_query, run_single


@dataclass
class PreviewOutcome:
    status: str  # "approved" or "cancelled"
    summary: str
    note: str = ""


async def runPreviewAndWait(
    *,
    executionId: str,
    userId: str,
    summary: str,
    pollIntervalSeconds: float = 1.0,
    timeoutSeconds: float = 600.0,
) -> PreviewOutcome:
    """Persist the preview, poll Neo4j, return the terminal state.

    The HTMX dashboard updates the node's `status` to `approved` or
    `cancelled`; this coroutine blocks on the poll until one of those
    states is reached or `timeoutSeconds` elapses (in which case the
    preview is treated as cancelled to fail safe).
    """
    nowIso = datetime.now(timezone.utc).isoformat()
    run_query(
        """
        MERGE (p:PreviewApproval {execution_id: $executionId})
          ON CREATE SET p.user_id = $userId,
                        p.status = 'pending',
                        p.summary = $summary,
                        p.created_at = $nowIso
          ON MATCH  SET p.status = 'pending',
                        p.summary = $summary,
                        p.updated_at = $nowIso
        """,
        executionId=executionId,
        userId=userId,
        summary=summary,
        nowIso=nowIso,
    )

    deadline = asyncio.get_event_loop().time() + timeoutSeconds
    while asyncio.get_event_loop().time() < deadline:
        record = run_single(
            """
            MATCH (p:PreviewApproval {execution_id: $executionId})
            RETURN p.status AS status, p.summary AS summary, coalesce(p.note, '') AS note
            """,
            executionId=executionId,
        )
        if record is None:
            break
        status = str(record.get("status") or "pending")
        if status in ("approved", "cancelled"):
            return PreviewOutcome(
                status=status,
                summary=str(record.get("summary") or summary),
                note=str(record.get("note") or ""),
            )
        await asyncio.sleep(pollIntervalSeconds)

    return PreviewOutcome(status="cancelled", summary=summary, note="preview_timeout")
