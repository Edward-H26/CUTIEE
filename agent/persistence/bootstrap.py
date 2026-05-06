"""Idempotent Cypher bootstrap: install CUTIEE's constraints and indexes.

Safe to run multiple times. Every statement uses `IF NOT EXISTS`, so re-runs
are no-ops. We also catch `IndexAlreadyExists` errors from prior
miramemoria-style installs whose indexes shadow CUTIEE constraints.
"""

from __future__ import annotations

import logging
import sys

from neo4j.exceptions import ClientError

from .neo4j_client import run_query

_logger = logging.getLogger("cutiee.bootstrap")

CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT user_id           IF NOT EXISTS FOR (u:User)               REQUIRE u.id           IS UNIQUE",
    "CREATE CONSTRAINT user_email        IF NOT EXISTS FOR (u:User)               REQUIRE u.email        IS UNIQUE",
    "CREATE CONSTRAINT user_google_sub   IF NOT EXISTS FOR (u:User)               REQUIRE u.google_sub   IS UNIQUE",
    "CREATE CONSTRAINT user_pref_user    IF NOT EXISTS FOR (p:UserPreference)     REQUIRE p.user_id      IS UNIQUE",
    "CREATE CONSTRAINT session_key       IF NOT EXISTS FOR (s:Session)            REQUIRE s.session_key  IS UNIQUE",
    "CREATE CONSTRAINT task_id           IF NOT EXISTS FOR (t:Task)               REQUIRE t.id           IS UNIQUE",
    "CREATE CONSTRAINT execution_id      IF NOT EXISTS FOR (e:Execution)          REQUIRE e.id           IS UNIQUE",
    "CREATE CONSTRAINT active_execution_user IF NOT EXISTS FOR (e:Execution)      REQUIRE e.active_user_id IS UNIQUE",
    "CREATE CONSTRAINT step_id           IF NOT EXISTS FOR (s:Step)               REQUIRE s.id           IS UNIQUE",
    "CREATE CONSTRAINT template_id       IF NOT EXISTS FOR (t:ProceduralTemplate) REQUIRE t.id           IS UNIQUE",
    "CREATE CONSTRAINT bullet_id         IF NOT EXISTS FOR (b:MemoryBullet)       REQUIRE b.id           IS UNIQUE",
    # Phase 9 CDP tab fencing: require user_id on every bullet so a
    # mis-issued query without a user filter fails at the database
    # instead of silently cross-reading.
    "CREATE CONSTRAINT bullet_user_scope IF NOT EXISTS FOR (b:MemoryBullet)       REQUIRE b.user_id      IS NOT NULL",
    "CREATE CONSTRAINT audit_id          IF NOT EXISTS FOR (a:AuditEntry)         REQUIRE a.id           IS UNIQUE",
    "CREATE CONSTRAINT progress_exec_id  IF NOT EXISTS FOR (p:ProgressSnapshot)   REQUIRE p.execution_id IS UNIQUE",
    # Phase 4 budget cap ledger; Phase 7 heartbeat plus approval queue;
    # Phase 16 pre-run preview. Each structure is keyed on a natural
    # identifier so the MERGE-based writes at their call sites are
    # idempotent.
    "CREATE CONSTRAINT cost_ledger_key   IF NOT EXISTS FOR (l:CostLedger)         REQUIRE (l.user_id, l.hour_key) IS UNIQUE",
    # The action-approval flow is in-process (apps/tasks/approval_queue.py)
    # and never writes to Neo4j, so no :ActionApproval constraint is
    # declared here. Add one back only if the queue moves into Neo4j.
    "CREATE CONSTRAINT preview_approval_id IF NOT EXISTS FOR (p:PreviewApproval)  REQUIRE p.execution_id IS UNIQUE",
    # Screenshot store writes MERGE (:Screenshot {execution_id, step_index}).
    # Without this composite constraint Neo4j scans every :Screenshot node on
    # each write, which scales linearly in stored screenshots. The uniqueness
    # constraint also blocks duplicate inserts when a retry races a retry.
    "CREATE CONSTRAINT screenshot_exec_step IF NOT EXISTS FOR (s:Screenshot)      REQUIRE (s.execution_id, s.step_index) IS UNIQUE",
]

INDEXES: list[str] = [
    "CREATE INDEX template_domain       IF NOT EXISTS FOR (t:ProceduralTemplate) ON (t.domain)",
    "CREATE INDEX template_stale        IF NOT EXISTS FOR (t:ProceduralTemplate) ON (t.stale)",
    "CREATE INDEX bullet_type           IF NOT EXISTS FOR (b:MemoryBullet)       ON (b.memory_type)",
    "CREATE INDEX bullet_content_hash   IF NOT EXISTS FOR (b:MemoryBullet)       ON (b.content_hash)",
    "CREATE INDEX bullet_user           IF NOT EXISTS FOR (b:MemoryBullet)       ON (b.user_id)",
    "CREATE INDEX audit_user_time       IF NOT EXISTS FOR (a:AuditEntry)         ON (a.user_id, a.timestamp)",
    "CREATE INDEX progress_updated_at   IF NOT EXISTS FOR (p:ProgressSnapshot)   ON (p.updated_at)",
    # Phase 4, 7, 16 support indexes so polling is cheap.
    "CREATE INDEX cost_ledger_user      IF NOT EXISTS FOR (l:CostLedger)         ON (l.user_id, l.hour_key)",
    "CREATE INDEX cost_ledger_day       IF NOT EXISTS FOR (l:CostLedger)         ON (l.user_id, l.day_key)",
    # action_approval_exec index omitted for the same reason as the
    # constraint: the queue is in-process and writes nothing to Neo4j.
    "CREATE INDEX preview_approval_stat IF NOT EXISTS FOR (p:PreviewApproval)    ON (p.status)",
]


def bootstrap() -> None:
    _logger.info("Installing CUTIEE Neo4j constraints and indexes...")
    for statement in CONSTRAINTS + INDEXES:
        label = statement.split("(")[1].split(":")[1].split(")")[0]
        name = statement.split()[2]
        try:
            run_query(statement)
            _logger.info("  ok    %-30s  :%s", name, label)
        except (RuntimeError, ClientError) as exc:
            # Pre-existing miramemoria-style indexes can shadow our
            # constraints; report and continue rather than aborting.
            if "IndexAlreadyExists" in str(exc) or "already exists" in str(exc).lower():
                _logger.info("  skip  %-30s  :%s (already present)", name, label)
                continue
            raise
    _logger.info("Done.")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        bootstrap()
    except RuntimeError as exc:
        _logger.error("ERROR: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
