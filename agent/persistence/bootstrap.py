"""Idempotent Cypher bootstrap: install CUTIEE's constraints and indexes.

Safe to run multiple times. Every statement uses `IF NOT EXISTS`, so re-runs
are no-ops.
"""
from __future__ import annotations

import sys

from agent.persistence.neo4j_client import run_query

CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT user_id         IF NOT EXISTS FOR (u:User)               REQUIRE u.id           IS UNIQUE",
    "CREATE CONSTRAINT user_email      IF NOT EXISTS FOR (u:User)               REQUIRE u.email        IS UNIQUE",
    "CREATE CONSTRAINT session_key     IF NOT EXISTS FOR (s:Session)            REQUIRE s.session_key  IS UNIQUE",
    "CREATE CONSTRAINT task_id         IF NOT EXISTS FOR (t:Task)               REQUIRE t.id           IS UNIQUE",
    "CREATE CONSTRAINT execution_id    IF NOT EXISTS FOR (e:Execution)          REQUIRE e.id           IS UNIQUE",
    "CREATE CONSTRAINT step_id         IF NOT EXISTS FOR (s:Step)               REQUIRE s.id           IS UNIQUE",
    "CREATE CONSTRAINT template_id     IF NOT EXISTS FOR (t:ProceduralTemplate) REQUIRE t.id           IS UNIQUE",
    "CREATE CONSTRAINT bullet_id       IF NOT EXISTS FOR (b:MemoryBullet)       REQUIRE b.id           IS UNIQUE",
    "CREATE CONSTRAINT fact_id         IF NOT EXISTS FOR (f:SemanticFact)       REQUIRE f.id           IS UNIQUE",
    "CREATE CONSTRAINT audit_id        IF NOT EXISTS FOR (a:AuditEntry)         REQUIRE a.id           IS UNIQUE",
]

INDEXES: list[str] = [
    "CREATE INDEX template_domain    IF NOT EXISTS FOR (t:ProceduralTemplate) ON (t.domain)",
    "CREATE INDEX template_stale     IF NOT EXISTS FOR (t:ProceduralTemplate) ON (t.stale)",
    "CREATE INDEX bullet_type        IF NOT EXISTS FOR (b:MemoryBullet)       ON (b.memory_type)",
    "CREATE INDEX bullet_content_hash IF NOT EXISTS FOR (b:MemoryBullet)      ON (b.content_hash)",
    "CREATE INDEX audit_user_time    IF NOT EXISTS FOR (a:AuditEntry)         ON (a.user_id, a.timestamp)",
]


def bootstrap() -> None:
    print("Installing CUTIEE Neo4j constraints and indexes...")
    for statement in CONSTRAINTS + INDEXES:
        run_query(statement)
        label = statement.split("(")[1].split(":")[1].split(")")[0]
        print(f"  ok  {statement.split()[2]:30s}  :{label}")
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
