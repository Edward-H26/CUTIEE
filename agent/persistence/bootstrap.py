"""Idempotent Cypher bootstrap: install CUTIEE's constraints and indexes.

Safe to run multiple times. Every statement uses `IF NOT EXISTS`, so re-runs
are no-ops. We also catch `IndexAlreadyExists` errors from prior
miramemoria-style installs whose indexes shadow CUTIEE constraints.
"""
from __future__ import annotations

import sys

from neo4j.exceptions import ClientError

from agent.persistence.neo4j_client import run_query

CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT user_id           IF NOT EXISTS FOR (u:User)               REQUIRE u.id           IS UNIQUE",
    "CREATE CONSTRAINT user_email        IF NOT EXISTS FOR (u:User)               REQUIRE u.email        IS UNIQUE",
    "CREATE CONSTRAINT session_key       IF NOT EXISTS FOR (s:Session)            REQUIRE s.session_key  IS UNIQUE",
    "CREATE CONSTRAINT task_id           IF NOT EXISTS FOR (t:Task)               REQUIRE t.id           IS UNIQUE",
    "CREATE CONSTRAINT execution_id      IF NOT EXISTS FOR (e:Execution)          REQUIRE e.id           IS UNIQUE",
    "CREATE CONSTRAINT step_id           IF NOT EXISTS FOR (s:Step)               REQUIRE s.id           IS UNIQUE",
    "CREATE CONSTRAINT template_id       IF NOT EXISTS FOR (t:ProceduralTemplate) REQUIRE t.id           IS UNIQUE",
    "CREATE CONSTRAINT bullet_id         IF NOT EXISTS FOR (b:MemoryBullet)       REQUIRE b.id           IS UNIQUE",
    "CREATE CONSTRAINT fact_id           IF NOT EXISTS FOR (f:SemanticFact)       REQUIRE f.id           IS UNIQUE",
    "CREATE CONSTRAINT audit_id          IF NOT EXISTS FOR (a:AuditEntry)         REQUIRE a.id           IS UNIQUE",
    "CREATE CONSTRAINT progress_exec_id  IF NOT EXISTS FOR (p:ProgressSnapshot)   REQUIRE p.execution_id IS UNIQUE",
]

INDEXES: list[str] = [
    "CREATE INDEX template_domain       IF NOT EXISTS FOR (t:ProceduralTemplate) ON (t.domain)",
    "CREATE INDEX template_stale        IF NOT EXISTS FOR (t:ProceduralTemplate) ON (t.stale)",
    "CREATE INDEX bullet_type           IF NOT EXISTS FOR (b:MemoryBullet)       ON (b.memory_type)",
    "CREATE INDEX bullet_content_hash   IF NOT EXISTS FOR (b:MemoryBullet)       ON (b.content_hash)",
    "CREATE INDEX audit_user_time       IF NOT EXISTS FOR (a:AuditEntry)         ON (a.user_id, a.timestamp)",
    "CREATE INDEX progress_updated_at   IF NOT EXISTS FOR (p:ProgressSnapshot)   ON (p.updated_at)",
]


def bootstrap() -> None:
    print("Installing CUTIEE Neo4j constraints and indexes...")
    for statement in CONSTRAINTS + INDEXES:
        label = statement.split("(")[1].split(":")[1].split(")")[0]
        name = statement.split()[2]
        try:
            run_query(statement)
            print(f"  ok    {name:30s}  :{label}")
        except (RuntimeError, ClientError) as exc:
            # Pre-existing miramemoria-style indexes can shadow our
            # constraints; report and continue rather than aborting.
            if "IndexAlreadyExists" in str(exc) or "already exists" in str(exc).lower():
                print(f"  skip  {name:30s}  :{label} (already present)")
                continue
            raise
    print("Done.")


def main() -> int:
    try:
        bootstrap()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file = sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
