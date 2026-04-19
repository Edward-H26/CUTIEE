# CUTIEE ULTRAREVIEW Run — 2026-04-19

End-to-end review of the setup, executed via Playwright MCP browser automation against a local Django server backed by Neo4j (Homebrew-installed).

## Environment

| Component | Version / Source | Status |
|-----------|------------------|--------|
| Python | 3.13.9 (Anaconda) | ok |
| uv | 0.11.7 | ok |
| Django | 6.0.4 | ok |
| neo4j (Python driver) | 6.1.0 | ok |
| Neo4j server | 2026.03.1 (Homebrew) | running on bolt://localhost:7687 |
| Playwright | 1.58.0 (via pytest-playwright) | ok (MCP-driven in this review) |
| llama-server (Qwen3.5 0.8B) | not started in this session | GGUF download and start pending |
| Gemini 3.1 | production mode only | cloud endpoint, not exercised locally |

## Review matrix outcome

| # | Cell | Verification | Result |
|---|------|--------------|--------|
| 1 | Neo4j reachability | `cypher-shell` returns 1 | ok |
| 2 | Bootstrap idempotence | `python -m agent.persistence.bootstrap` installs 10 constraints + 5 indexes | ok, re-runnable |
| 3 | Django `check` | `manage.py check` | 0 issues |
| 4 | URL surface (anonymous) | `/` 200, `/tasks|memory|audit/` 302 to login, `/accounts/login|signup/` 200 | ok |
| 5 | Landing page | rendered in browser, matches miramemoria aesthetic (gradient hero, glass cards, pulsing pill, cost strip) | ok (see `screenshots/landing.png`) |
| 6 | Email+password login | Django superuser signs in successfully, session persists across navigation | ok (see `screenshots/tasks-authenticated.png`) |
| 7 | Django → Neo4j user mirror | `post_save` signal creates `:User {id: <pk>}` on user create | ok, verified via Cypher |
| 8 | Protected pages (authenticated) | Tasks / Memory / Audit all render with nav | ok |
| 9 | Memory bullets end-to-end | two seeded `:MemoryBullet` nodes surface via `memory_app.repo.list_bullets_for_user` and render in template with all three strength channels, tags, helpful/harmful | ok (see `screenshots/memory-bullets.png`) |
| 10 | Audit entries end-to-end | seeded `:AuditEntry` surfaces via `audit.repo.list_audit_for_user` and renders in glass-surface table | ok (see `screenshots/audit.png`) |
| 11 | Logout flow | click Log out, session cleared, redirect to landing | ok |
| 12 | Console errors | landing page has one 404 on `favicon.ico` (cosmetic); no JS errors elsewhere | acceptable |

## Neo4j inventory at end of review

```
MATCH (n:User)         → 1 node   (review@cutiee.dev, id="2")
MATCH (n:MemoryBullet) → 2 nodes  (bullet-proc-001 procedural, bullet-sem-002 episodic)
MATCH (n:AuditEntry)   → 1 node   (task_run, tier 1, cost $0, qwen3.5-0.8b)
SHOW CONSTRAINTS       → 10 uniqueness constraints (9 id + 1 email)
SHOW INDEXES           → 5 secondary indexes (template_domain, template_stale, bullet_type, bullet_content_hash, audit_user_time)
```

## Architectural decisions validated in this run

1. **Neo4j-as-default-database** — All domain data (bullets, audit, user mirror) round-trips through Cypher. Django's ORM touches only `auth_user`, `django_session`, `allauth_*` tables in a small on-disk SQLite scoped to framework internals. That keeps the design consistent with the plan while sidestepping the "allauth wants a numeric FK" constraint that blocked the initial UUID-only approach.
2. **Ported Neo4j client** — `agent/persistence/neo4j_client.py` matches miramemoria's `_run_query` / `_run_single` surface. The "fail loudly on missing config" policy works as designed — missing `NEO4J_BOLT_URL` raises `RuntimeError` with a remediation hint at settings import time.
3. **Three-strength bullet model** — The seeded bullets demonstrate the design: the procedural bullet scored 98 on `procedural_strength` with 6/12 on the other channels, while the episodic bullet scored 87 on `episodic_strength` with near-zero procedural. Retrieval and decay math land in Phase 2 of the plan.

## Known gaps after this review

- **llama-server (Qwen3.5 0.8B)** was not started in this session. The GGUF is not downloaded into `data/models/qwen/*.gguf`. `scripts/dev.sh` handles both when the user runs it locally.
- **Google OAuth** is wired via `django-allauth` but credentials are placeholders in this session. Clicking the "Google" link on the login page would 404 until `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` are set in `.env`.
- **Reflector → Quality Gate → Curator pipeline** (Phase 2 of the plan) is specified but not implemented in this first scaffold pass. The repos and bullet schema are ready to accept `DeltaUpdate` objects when the pipeline lands.
- **Task submission + live progress** (Phase 5) is a placeholder page. The orchestrator + router layers (Phase 1 / Phase 4) are not yet wired in.

## How to reproduce locally

```bash
# Prereqs (one-time)
brew install neo4j
brew services start neo4j
cypher-shell -a bolt://localhost:7687 -u neo4j -p neo4j -d system \
  "ALTER CURRENT USER SET PASSWORD FROM 'neo4j' TO 'cutiee-dev-password'"

cd /Users/edwardhu/Desktop/INFO490/CUTIEE
uv sync

# Bootstrap schema
CUTIEE_ENV=local \
  NEO4J_BOLT_URL=bolt://localhost:7687 \
  NEO4J_USERNAME=neo4j \
  NEO4J_PASSWORD=cutiee-dev-password \
  uv run python -m agent.persistence.bootstrap

# Migrate Django internals
CUTIEE_ENV=local ... uv run python manage.py migrate

# Seed a test user
CUTIEE_ENV=local ... DJANGO_SUPERUSER_USERNAME=review \
  DJANGO_SUPERUSER_EMAIL=review@cutiee.dev \
  DJANGO_SUPERUSER_PASSWORD=ReviewPass123! \
  uv run python manage.py createsuperuser --no-input

# Run
CUTIEE_ENV=local ... uv run python manage.py runserver 0.0.0.0:8000
```

Full env var block, see `.env.cutiee.template` at the repo root.
