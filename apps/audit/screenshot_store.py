"""Per-step screenshot store backed by Neo4j with TTL-based cleanup.

Each Computer Use step captures a PNG of the page the model just saw.
Storing those PNGs lets users scrub through the agent's visual context
on the task detail page, which is essential for diagnosing the
"OK steps but nothing changed" failure mode.

Storage shape:
    (:Screenshot {
        execution_id: str,
        step_index: int,
        data_b64:   str   (base64-encoded PNG bytes),
        size_bytes: int,
        created_at: datetime
    })

Two safety mechanisms keep the AuraDB Free 50MB quota safe under abuse:

  1. **Lazy TTL sweep** on every `save()` deletes anything older than
     `ttlDays`. No cron needed.
  2. **Global byte cap** (`maxTotalBytes`, default 40 MB): when the total
     stored size approaches the Aura quota, new saves silently drop
     instead of pushing the database past its limit. A logged warning
     surfaces so operators see the throttle.

Hit rate matters: don't sweep on `fetch()` because the post-finish
polls would pay for cleanup nobody asked for.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

from agent.harness.env_utils import envInt
from agent.persistence.neo4j_client import run_query, run_single

DEFAULT_TTL_DAYS = 3
DEFAULT_MAX_TOTAL_BYTES = 40 * 1024 * 1024  # 40 MB; Aura free tier is 50 MB

_logger = logging.getLogger("cutiee.screenshot_store")


@dataclass
class ScreenshotRecord:
    executionId: str
    stepIndex: int
    sizeBytes: int


class Neo4jScreenshotStore:
    def __init__(
        self,
        ttlDays: int | None = None,
        maxTotalBytes: int | None = None,
    ) -> None:
        self.ttlDays = (
            ttlDays
            if ttlDays is not None
            else envInt("CUTIEE_SCREENSHOT_TTL_DAYS", DEFAULT_TTL_DAYS)
        )
        self.maxTotalBytes = (
            maxTotalBytes
            if maxTotalBytes is not None
            else envInt("CUTIEE_SCREENSHOT_MAX_TOTAL_BYTES", DEFAULT_MAX_TOTAL_BYTES)
        )

    def save(self, executionId: str, stepIndex: int, pngBytes: bytes) -> ScreenshotRecord | None:
        """Persist a PNG; returns None when the global byte cap is exceeded.

        Sweep first so the cap check sees the post-TTL footprint, then
        enforce the cap before adding more bytes. Callers must treat
        the result as best-effort (returns None on cap-hit, never raises).
        """
        size = len(pngBytes)
        # Sweep stale entries before the cap check so old screenshots
        # don't artificially inflate the "current" total.
        self._sweep()

        currentBytes = self._totalBytes()
        if currentBytes + size > self.maxTotalBytes:
            _logger.warning(
                "Screenshot save dropped: global byte cap reached "
                "(current=%s + new=%s > cap=%s). Older screenshots will "
                "free space at the next TTL sweep.",
                currentBytes,
                size,
                self.maxTotalBytes,
            )
            return None

        encoded = base64.b64encode(pngBytes).decode("ascii")
        run_query(
            """
            MERGE (s:Screenshot {execution_id: $eid, step_index: $idx})
            SET s.data_b64 = $data,
                s.size_bytes = $size,
                s.created_at = datetime()
            """,
            eid=str(executionId),
            idx=int(stepIndex),
            data=encoded,
            size=size,
        )
        return ScreenshotRecord(
            executionId=str(executionId),
            stepIndex=int(stepIndex),
            sizeBytes=size,
        )

    def _totalBytes(self) -> int:
        row = run_single("MATCH (s:Screenshot) RETURN coalesce(sum(s.size_bytes), 0) AS total")
        return int(row["total"]) if row else 0

    def fetch(self, executionId: str, stepIndex: int) -> bytes | None:
        row = run_single(
            """
            MATCH (s:Screenshot {execution_id: $eid, step_index: $idx})
            RETURN s.data_b64 AS data
            """,
            eid=str(executionId),
            idx=int(stepIndex),
        )
        if row is None or not row.get("data"):
            return None
        try:
            return base64.b64decode(row["data"])
        except (TypeError, ValueError):
            return None

    def listForExecution(self, executionId: str) -> list[int]:
        rows = run_query(
            """
            MATCH (s:Screenshot {execution_id: $eid})
            RETURN s.step_index AS idx
            ORDER BY s.step_index ASC
            """,
            eid=str(executionId),
        )
        return [int(row["idx"]) for row in rows]

    def deleteForExecution(self, executionId: str) -> int:
        rows = run_query(
            """
            MATCH (s:Screenshot {execution_id: $eid})
            WITH s, count(s) AS n
            DETACH DELETE s
            RETURN n AS deleted
            """,
            eid=str(executionId),
        )
        return int(rows[0]["deleted"]) if rows else 0

    def _sweep(self) -> None:
        run_query(
            """
            MATCH (s:Screenshot)
            WHERE s.created_at < datetime() - duration({days: $days})
            DETACH DELETE s
            """,
            days=int(self.ttlDays),
        )
