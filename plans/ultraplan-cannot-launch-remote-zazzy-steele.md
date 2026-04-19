# CUTIEE — Django Implementation Plan for INFO490 Final (A10)

> **For agentic workers:** Implement task-by-task. Each task uses TDD. Stop at the review checkpoints and show test output before proceeding. Never skip a phase.

**Project name:** **CUTIEE** = **C**omputer **U**se agent**I**c-framework with **T**oken-efficient harn**E**ss **E**ngineering (renamed from CUITEEE).

**Goal:** Ship a Django web application at `https://github.com/Edward-H26/CUTIEE.git` that demonstrates the CUTIEE framework (procedural memory replay, temporal recency pruning, multi-model routing, self-evolving templates) as a meaningful AI feature integrated into a real user flow. Two deployment targets: local dev runs Qwen3.5 0.8B only; production on Render runs Gemini 3.1 only. Satisfies all four parts of the INFO490 A10 assignment.

**Architecture:** Django project `cutiee_site` with user-facing apps (`accounts`, `tasks`, `memory_app`, `audit`, `landing`), plus a plain-Python `agent/` package containing the CUTIEE harness, browser controller, memory/pruning/routing mechanisms, and environment-specific VLM clients. Django templates render the UI. **All application data — users, sessions, tasks, executions, steps, memory bullets, audit entries — persists in Neo4j** via the official Python driver, accessed through Cypher-backed repository modules (not Django ORM). Django's framework tables (contenttypes, admin, sites, allauth) live in an in-memory SQLite that is re-created on every process start. The `CUTIEE_ENV` environment variable selects either the local Qwen stack or the production Gemini stack — never both.

**Visual design:** Inherited from `/Users/edwardhu/Desktop/INFO490/miramemoria`. Identical color tokens (`#6C86C0` primary, radial pink-blue-purple background gradient), Inter + Manrope fonts via Google Fonts, glass-morphism surfaces (`backdrop-filter: blur(20px)`), 64px header, 229px sidebar. The brand feels like the same product family as Memoria.

**Tech Stack:** Python 3.11+, Django 5.0+, Django REST Framework, `django-allauth[socialaccount]` (Google OAuth primary), Playwright 1.45+, llama-cpp-python (Qwen3.5 0.8B GGUF — dev only), `google-genai` SDK (Gemini 3.1 — production only), **Neo4j 5 (default database via the official `neo4j` Python driver — Dockerized locally, Neo4j AuraDB Free in production)**, FastEmbed (embeddings only, written into Neo4j as JSON strings), HTMX (live progress + VLM-readiness polling), Tailwind CSS v4 (precompiled), Chart.js (cost visualizations), pytest + pytest-django + pytest-playwright, `uv`, Gunicorn + Whitenoise for Render deployment.

**Failure policy:** No silent fallbacks. Missing dependencies, missing model files, missing API keys, unset `CUTIEE_ENV`, an unreachable Neo4j bolt endpoint, or unreachable VLM servers all raise a clear error with actionable remediation. The user picks the model and database explicitly, and the system fails loudly when requirements are not met.

---

## Database Architecture — Neo4j as Default

CUTIEE uses Neo4j 5 as the default database for all domain data. The choice reflects three facts about the workload. First, procedural memory is a graph: a template points to an ordered sequence of parameterized steps, each with verification nodes, and templates evolve into successor templates through self-healing edges. Second, miramemoria (our sibling project at `/Users/edwardhu/Desktop/INFO490/miramemoria`) already ships a complete Neo4j persistence layer via the official `neo4j` Python driver, which we reuse verbatim to avoid redundant infrastructure work. Third, a single graph database lets CUTIEE serve both authentication and domain reads from the same connection pool, so the system runs with no SQLite footprint at all.

### Persistence strategy

We import three files directly from miramemoria and adapt them for the CUTIEE label namespace:

- `app/services/neo4j_memory.py` → `agent/persistence/neo4j_client.py` (driver factory, constraint bootstrap, `_run_query`, `_run_single` helpers)
- `app/services/neo4j_auth_backend.py` → `apps/accounts/neo4j_auth_backend.py` (Django `AUTHENTICATION_BACKENDS` entry backed by Neo4j `User` nodes; works with `django-allauth` via a thin user-proxy adapter)
- `app/services/neo4j_session_backend.py` → `cutiee_site/neo4j_session_backend.py` (Django session engine that stores sessions as `(:Session {key, data, expire})` nodes)

By wiring `SESSION_ENGINE` to the Neo4j session backend and prepending the Neo4j auth backend to `AUTHENTICATION_BACKENDS`, Django never touches a relational database. We still run `python manage.py migrate` once on an in-memory SQLite URL so that `contenttypes`, `admin`, and `allauth` tables exist for the framework's internal bookkeeping, but no application data lives there and the file never hits disk beyond Django's own startup probe.

### Label namespace and constraints

```cypher
CREATE CONSTRAINT user_id         IF NOT EXISTS FOR (u:User)              REQUIRE u.id         IS UNIQUE;
CREATE CONSTRAINT user_email      IF NOT EXISTS FOR (u:User)              REQUIRE u.email      IS UNIQUE;
CREATE CONSTRAINT session_key     IF NOT EXISTS FOR (s:Session)           REQUIRE s.session_key IS UNIQUE;
CREATE CONSTRAINT task_id         IF NOT EXISTS FOR (t:Task)              REQUIRE t.id         IS UNIQUE;
CREATE CONSTRAINT execution_id    IF NOT EXISTS FOR (e:Execution)         REQUIRE e.id         IS UNIQUE;
CREATE CONSTRAINT step_id         IF NOT EXISTS FOR (s:Step)              REQUIRE s.id         IS UNIQUE;
CREATE CONSTRAINT template_id     IF NOT EXISTS FOR (t:ProceduralTemplate) REQUIRE t.id        IS UNIQUE;
CREATE CONSTRAINT fact_id         IF NOT EXISTS FOR (f:SemanticFact)      REQUIRE f.id         IS UNIQUE;
CREATE CONSTRAINT audit_id        IF NOT EXISTS FOR (a:AuditEntry)        REQUIRE a.id         IS UNIQUE;
CREATE INDEX template_domain      IF NOT EXISTS FOR (t:ProceduralTemplate) ON (t.domain);
CREATE INDEX template_stale       IF NOT EXISTS FOR (t:ProceduralTemplate) ON (t.stale);
CREATE INDEX audit_user_time      IF NOT EXISTS FOR (a:AuditEntry)        ON (a.user_id, a.timestamp);
```

### Relationship model

```
(User)-[:OWNS]->(Task)
(User)-[:HOLDS]->(SemanticFact {is_credential: bool})
(User)-[:RECEIVED]->(AuditEntry)
(Task)-[:EXECUTED_AS {run_index}]->(Execution)
(Execution)-[:HAS_STEP {index}]->(Step)
(Execution)-[:REPLAYED_FROM]->(ProceduralTemplate)
(ProceduralTemplate)-[:HAS_STEP {index}]->(Step)
(ProceduralTemplate)-[:SUPERSEDED_BY {reason}]->(ProceduralTemplate)
(Step)-[:VERIFIED_BY]->(Verification)
(Step)-[:USED_MODEL {tier, cost_usd}]->(ModelCall)
```

Ordered relationships (`HAS_STEP {index: int}`) let us materialize step sequences with a single Cypher query; the `{index}` property is the single source of truth for ordering.

### Environment targets

| Environment | Neo4j endpoint | Credentials | How to start |
|-------------|----------------|-------------|--------------|
| `local` | `bolt://localhost:7687` | `neo4j` / set via `.env` | `docker compose up -d neo4j` (see Task 0.2.5) |
| `production` | `neo4j+s://<dbid>.databases.neo4j.io` | AuraDB Free credentials | Create a free AuraDB instance at https://console.neo4j.io/ |

Render deployment reads `NEO4J_BOLT_URL`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` from the dashboard (`sync: false`). The Free AuraDB tier provides 200k nodes + 400k relationships, well above CUTIEE's expected workload for the INFO490 submission.

### Non-goals (database-layer)

- We do not ship a vector index inside Neo4j 5.x. Embeddings are stored as JSON-encoded `float32` arrays on `:ProceduralTemplate(embedding)` and ranked with an in-Python cosine routine. When the catalog exceeds ~5k templates we revisit; for the INFO490 submission this is fine.
- We do not use `neomodel` or `django-neomodel`. Raw Cypher via the official driver keeps CUTIEE's persistence surface identical to miramemoria, and avoids a second migration subsystem.
- We do not attempt to use Neo4j for static file serving or Django migrations — those remain in-memory or Whitenoise-backed.

---

## Context

The INFO490 A10 assignment is the semester's culmination. The user has already built a Django app (A1-A5), integrated APIs and auth, benchmarked AI models (A6-A7), built retrieval systems (A8), and integrated AI into the app (A9). A10 refines and integrates everything into a coherent, production-aware intelligent web application. The rubric allocates 30 points to AI integration, 25 points each to Django quality and evaluation, and 15 points to cost and production awareness. A purely API-based AI feature receives reduced credit.

CUTIEE is the AI feature: a hybrid computer-use agent that routes each GUI action through a multi-tier pipeline, with a self-evolving procedural memory that updates templates when the underlying UI changes. In local development, all tiers run Qwen3.5 0.8B (a small CPU-friendly model) with varied prompts and context budgets, so the developer experience is fully offline. In production on Render, all tiers run Gemini 3.1 (Google's newest model at deploy time) with varied sizes — for example `gemini-3.1-flash-lite` for simple clicks, `gemini-3.1-flash` for navigation, and `gemini-3.1-pro` for complex reasoning. Procedural memory replay delivers zero-cost recurring tasks in both environments. Temporal recency pruning keeps context bounded across long workflows. Self-healing templates re-ground via a larger-tier model when a step fails verification, then patch themselves for future runs.

## Pre-Flight Actions (Before Starting Phase 0)

Plan mode forbids me from running these — the user (or a future session after plan approval) must execute them first:

```bash
# 1) Rename the directory
mv /Users/edwardhu/Desktop/INFO490/CUITEEE /Users/edwardhu/Desktop/INFO490/CUTIEE
cd /Users/edwardhu/Desktop/INFO490/CUTIEE

# 2) Initialize git and connect to the GitHub remote
git init
git branch -M main
git remote add origin https://github.com/Edward-H26/CUTIEE.git

# 3) Create .env (real secrets) and .env.example (template) — files listed in Task 0.2 below
#    These are created by the agent once plan mode is exited.

# 4) Re-run /ultraplan now that a git repo exists
```

After the directory rename, all plan references to the old path `/Users/edwardhu/Desktop/INFO490/CUITEEE/` apply to `/Users/edwardhu/Desktop/INFO490/CUTIEE/`. The plan file itself will need to move with the directory (it lives at `plans/ultraplan-cannot-launch-remote-zazzy-steele.md`).

## INFO490 Part-by-Part Mapping

| Assignment Part | Deliverable | Phase |
|-----------------|-------------|-------|
| Part 1: Product Refinement | `docs/part1_product_refinement.md` (1-2 page write-up + flow diagram) | Phase 0 |
| Part 2: Django System | `cutiee_site/`, `apps/*` with models/views/templates/auth/JSON API/data viz | Phases 1, 5 |
| Part 3: AI Integration | `agent/` package with environment-aware Qwen / Gemini + three mechanisms | Phases 2, 3, 4 |
| Part 4.1: System Evaluation | `docs/evaluation/test_cases.md` (5+ real-world Sheets/Slides demos) | Phase 7 |
| Part 4.2: Failure Analysis | `docs/evaluation/failure_analysis.md` (2+ cases) | Phase 7 |
| Part 4.3: Improvement | `docs/evaluation/improvement.md` (before/after) | Phase 7 |
| Part 4.4: Cost & Resource | `docs/evaluation/cost_comparison.md` + `scripts/benchmark_costs.py` | Phase 7 |
| Part 4.5: Production Readiness | `docs/evaluation/production_readiness.md` + Render deploy config | Phase 7 |
| Deliverable: Technical Report | `docs/technical_report.md` → PDF via pandoc | Phase 7 |
| Deliverable: README.md | Root README with setup for both dev and Render | Phase 7 |
| Deliverable: README_AI.md | AI workflow doc | Phase 7 |
| Deliverable: GitHub Repo | Pushed to `https://github.com/Edward-H26/CUTIEE.git` | After Phase 7 (user commits) |

## Model Stack by Environment

`CUTIEE_ENV` is the single switch. Unset raises an error.

| `CUTIEE_ENV` | Tier 1 | Tier 2 | Tier 3 | Notes |
|--------------|--------|--------|--------|-------|
| `local` | Qwen3.5 0.8B `/simple` prompt | Qwen3.5 0.8B `/general` prompt | Qwen3.5 0.8B `/full-context` prompt | `GEMINI_API_KEY` must NOT be set. No network needed after GGUF download. |
| `production` | `gemini-3.1-flash-lite` | `gemini-3.1-flash` | `gemini-3.1-pro` | `GEMINI_API_KEY` required. No Qwen server required. Deployed on Render. |

Tier escalation, confidence thresholds, and the router's behavior are identical across environments — only the model instances change.

## Project Structure (Post-Rename)

```
CUTIEE/                                    (formerly CUITEEE)
├── .env                                   (gitignored, created locally)
├── .env.example
├── .gitignore
├── CLAUDE.md
├── README.md
├── README_AI.md
├── manage.py
├── pyproject.toml
├── render.yaml                            (Render deployment config)
│
├── cutiee_site/                           (Django project settings)
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
├── apps/                                  (Django apps, user-facing)
│   ├── accounts/                          (login/logout/signup)
│   ├── tasks/                             (Task, Execution, Step models + views + JSON API)
│   ├── memory_app/                        (ProceduralTemplate, SemanticFact)
│   └── audit/                             (immutable AuditEntry)
│
├── agent/                                 (CUTIEE framework, plain Python)
│   ├── harness/                           (state.py, orchestrator.py, config.py)
│   ├── browser/                           (controller.py, dom_extractor.py)
│   ├── memory/                            (procedural.py, replay.py, semantic.py, episodic.py)
│   ├── pruning/                           (context_window.py, fg_bg_decomposer.py, summarizer.py)
│   ├── routing/
│   │   ├── router.py
│   │   ├── factory.py                     (env-aware client assembly)
│   │   ├── difficulty_classifier.py
│   │   ├── confidence_probe.py
│   │   └── models/
│   │       ├── base.py                    (VLMClient abstract)
│   │       ├── qwen_local.py              (Qwen3.5 0.8B via llama-server)
│   │       ├── gemini_cloud.py            (Gemini 3.1 variants)
│   │       └── mock.py                    (deterministic test double)
│   └── safety/                            (risk_classifier.py, approval_gate.py, audit.py)
│
├── demo_sites/                            (Flask targets for deterministic E2E)
│   ├── spreadsheet_site/app.py            (port 5001)
│   ├── slides_site/app.py                 (port 5002)
│   └── form_site/app.py                   (port 5003)
│
├── scripts/
│   ├── download_qwen.py
│   ├── start_llama_server.sh
│   ├── dev.sh                             (single-command dev: Django + background llama-server)
│   ├── start_demo_sites.py
│   └── benchmark_costs.py
│
├── templates/
│   └── base.html                          (inherits miramemoria layout)
│
├── static/
│   └── css/
│       ├── base.css                       (copied from miramemoria + renamed)
│       ├── main.css
│       ├── tailwind.input.css
│       └── tailwind.built.css
│
├── tests/
│   ├── conftest.py
│   ├── agent/
│   ├── apps/
│   └── integration/
│
├── docs/
│   ├── part1_product_refinement.md
│   ├── technical_report.md
│   ├── architecture.md
│   └── evaluation/
│       ├── test_cases.md
│       ├── failure_analysis.md
│       ├── improvement.md
│       ├── cost_comparison.md
│       └── production_readiness.md
│
└── data/                                  (gitignored runtime state)
    ├── models/qwen/*.gguf
    ├── db.sqlite3
    └── audit_logs/
```

## Coding Conventions

- Double quotes for strings
- Spaces around operators (`x = 1`)
- Comments only on important/complicated functions
- No `print` / `console.log` in production code
- Type hints everywhere
- camelCase variables/functions, PascalCase classes and Neo4j node labels, UPPER_SNAKE_CASE constants
- Boolean names start with `is`, `has`, `should`
- Dataclasses over dicts inside `agent/`; Cypher-backed repos under `apps/*/repo.py` for all persisted data (no Django ORM for domain models)
- Never execute `git commit` or `git push` — the user is the sole author. Plan uses "checkpoint" markers only.

## Execution Rules

1. **TDD mandatory** — failing test → implementation → passing test → next task.
2. **Stop at review checkpoints** — Phase 1 end is mandatory per user request.
3. **Do not skip phases** — Phase N green before Phase N+1 starts.
4. **No silent fallbacks** — missing dependency or key raises immediately.

---

# Phase 0 — Environment, Django Project, Product Refinement (Days 1-3)

**Goal:** A fresh clone (or post-rename repo) runs `uv sync && uv run python manage.py migrate && uv run python manage.py runserver` and loads the Django welcome page. Qwen downloads in `local` mode. Gemini key is configured for `production` mode. Part 1 doc drafted.

### Task 0.1: Write Part 1 Product Refinement

**File:** `docs/part1_product_refinement.md` (1-2 pages)

- [ ] **Step 1**: Write the doc covering:
  - **Refined Problem Statement**: Computer-use agents cost $0.30+ per task on cloud VLMs. CUTIEE reduces this to near-zero for recurring tasks via procedural memory replay, keeps context bounded via temporal recency pruning, and routes each action to the cheapest viable tier. The **self-Evolving** aspect: templates mutate themselves when the underlying UI changes, so workflows remain valid as sites evolve.
  - **Target Users**: Non-technical end users who delegate recurring web workflows (spreadsheet edits, slide updates, form filling, inbox triage). Secondary: developers building CUA products.
  - **Final Feature Set**: Task submission flow, procedural memory dashboard (view/edit/delete templates), live cost tracker, audit log, safety approval gate for high-risk actions, user authentication, internal JSON API, environment-aware model stack.
  - **Deprioritized**: multi-user shared memory; browser extension (headless only); voice input (text task descriptions); cross-site template transfer (domain-scoped).
  - **User Flow**: Sign in → submit task → orchestrator checks procedural memory → if template matches, replay at $0 → otherwise run full pipeline with tier routing → template stored → audit + cost dashboards update.
  - **System Flow Diagram**: Mermaid diagram showing Django views → service layer → agent orchestrator → browser / memory / pruning / routing → Cypher repos → Neo4j graph.

### Task 0.2: Initialize Python project + Django

**Files (create):**
- `pyproject.toml`
- `.env.example`
- `.env`
- `.gitignore`
- `CLAUDE.md`
- `README.md` (stub; final in Phase 7)
- `manage.py` + `cutiee_site/*`

- [ ] **Step 1**: Write `pyproject.toml`:

```toml
[project]
name = "cutiee"
version = "0.1.0"
description = "Computer Use agentIc-framework with Token-efficient harnEss Engineering"
requires-python = ">=3.11"
dependencies = [
    "django>=5.0",
    "djangorestframework>=3.15",
    "django-environ>=0.11",
    "django-allauth[socialaccount]>=65.0",
    "playwright>=1.45",
    "llama-cpp-python>=0.3",
    "google-genai>=0.3",
    "neo4j>=5.26",                    # Official Neo4j Python driver (default database for all domain data)
    "fastembed>=0.3",                 # Text embeddings; stored as JSON arrays on :ProceduralTemplate nodes
    "numpy>=1.26",                    # Cosine similarity for embedding ranking
    "httpx>=0.27",
    "pydantic>=2.0",
    "python-dotenv>=1.0",
    "huggingface-hub>=0.24",
    "flask>=3.0",
    "gunicorn>=22.0",
    "whitenoise>=6.7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-django>=4.9",
    "pytest-playwright>=0.5",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "mypy>=1.11",
    "respx>=0.21",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
DJANGO_SETTINGS_MODULE = "cutiee_site.settings"
python_files = ["tests.py", "test_*.py", "*_tests.py"]
markers = [
    "slow: tests that take >5s",
    "local: tests requiring CUTIEE_ENV=local and a running llama-server",
    "production: tests requiring CUTIEE_ENV=production and GEMINI_API_KEY",
    "integration: E2E tests against demo sites",
    "showcase: real-world demos requiring a logged-in Playwright storage_state",
]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 2**: Write `.env.example`:

```bash
# ── Deployment environment ────────────────────────────────────────────────────
# Required. Must be "local" or "production". No default — unset raises an error.
CUTIEE_ENV=local

# ── Django ────────────────────────────────────────────────────────────────────
DJANGO_SECRET_KEY="CHANGE_ME_TO_A_RANDOM_SECRET"
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1"

# ── Neo4j (default database — all domain data, auth, sessions) ────────────────
# Required in both local and production. No fallback.
# Local  : bolt://localhost:7687 (started via `docker compose up -d neo4j` in Task 0.2.5)
# Production: neo4j+s://<dbid>.databases.neo4j.io (AuraDB Free — create at https://console.neo4j.io)
NEO4J_BOLT_URL="bolt://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="cutiee-dev-password"
NEO4J_DATABASE="neo4j"

# Django's internal tables (contenttypes, migrations, allauth schema) live in an
# in-memory sqlite instance. All application data is in Neo4j.
DJANGO_INTERNAL_DB_URL="sqlite:///:memory:"

# ── Local (dev) stack: Qwen3.5 0.8B via llama-server ──────────────────────────
# Required when CUTIEE_ENV=local
QWEN_SERVER_URL="http://localhost:8001"
QWEN_MODEL_ID="Qwen/Qwen3.5-0.8B-Instruct-GGUF"
QWEN_GGUF_FILENAME="qwen3.5-0.8b-instruct-q4_k_m.gguf"

# ── Production (Render) stack: Gemini 3.1 ─────────────────────────────────────
# Required when CUTIEE_ENV=production
GEMINI_API_KEY=""
GEMINI_MODEL_TIER1="gemini-3.1-flash-lite"
GEMINI_MODEL_TIER2="gemini-3.1-flash"
GEMINI_MODEL_TIER3="gemini-3.1-pro"

# ── Runtime paths ─────────────────────────────────────────────────────────────
CUTIEE_DATA_DIR="./data"
CUTIEE_MODEL_DIR="./data/models"

# ── Router thresholds ─────────────────────────────────────────────────────────
CUTIEE_RECENCY_WINDOW=3
CUTIEE_TEMPLATE_MATCH_THRESHOLD=0.85
CUTIEE_CONFIDENCE_THRESHOLD_TIER1=0.75
CUTIEE_CONFIDENCE_THRESHOLD_TIER2=0.65
CUTIEE_CONFIDENCE_THRESHOLD_TIER3=0.50

# ── Google OAuth (required — primary auth flow) ───────────────────────────────
# Create credentials at https://console.cloud.google.com/apis/credentials
# Authorized redirect URI (local):      http://localhost:8000/auth/google/login/callback/
# Authorized redirect URI (production): https://cutiee.onrender.com/auth/google/login/callback/
GOOGLE_CLIENT_ID=""
GOOGLE_CLIENT_SECRET=""
```

- [ ] **Step 3**: Write `.env` (copied from `.env.example` with an auto-generated Django secret). Gitignored.

- [ ] **Step 4**: Write `.gitignore`:

```gitignore
# Django / runtime
*.log
__pycache__/
*.pyc
local_settings.py
db.sqlite3
db.sqlite3-journal
media/
staticfiles/

# Runtime data / gguf
data/
*.db
*.gguf

# Python
.venv/
*.egg-info/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/

# Environment
.env
.env.local

# Playwright
test-results/
playwright-report/
storage_state.json

# OS / IDE
.DS_Store
.vscode/
.idea/
*.swp
```

- [ ] **Step 5**: Write `CLAUDE.md` with: project overview (new CUTIEE name + acronym), architecture, `CUTIEE_ENV` switch, coding conventions, testing philosophy, and the explicit rule "No silent fallbacks. Missing deps or keys must error out."

- [ ] **Step 6**: Stub `README.md`:

```markdown
# CUTIEE

**Computer Use agentIc-framework with Token-efficient harnEss Engineering**

A Django web application that wraps any computer-use agent with three cost-reduction mechanisms: procedural memory replay, temporal recency pruning, and multi-tier model routing. Templates self-evolve when the underlying UI changes.

## Quick Start

### Local development (Qwen3.5 0.8B)

```bash
cp .env.example .env          # set CUTIEE_ENV=local, add GOOGLE_CLIENT_ID/SECRET
uv sync
uv run playwright install chromium
uv run python manage.py migrate
uv run python manage.py createsuperuser

# Single command — starts Django AND llama-server in parallel.
# Django on :8000 comes up immediately; Qwen warms up in the background (~5-10s from cache).
# The UI disables task submission until /api/vlm-health/ reports ready.
./scripts/dev.sh
```

The first run downloads the Qwen GGUF (~500MB) into `data/models/qwen/`. Subsequent runs use the cached file.

### Production (Render)

Set `CUTIEE_ENV=production` and `GEMINI_API_KEY` in the Render dashboard. The build command runs `uv sync && python manage.py collectstatic --no-input && python manage.py migrate`. The start command is `gunicorn cutiee_site.wsgi`.

See `docs/technical_report.md` for the full design document.
```

- [ ] **Step 7**: Install and scaffold:

```bash
uv sync
uv run playwright install chromium
uv run django-admin startproject cutiee_site .
```

### Task 0.2.5: Neo4j infrastructure (local Docker + AuraDB) and miramemoria integration

**Goal:** Bring Neo4j up in both environments, port miramemoria's persistence helpers, and install CUTIEE's constraints + indexes. Nothing else depends on a live database yet, so this is the right place to do the one-time bootstrap.

**Files (create):**
- `docker-compose.yml` (local Neo4j 5 service)
- `agent/persistence/__init__.py`
- `agent/persistence/neo4j_client.py` (ported from `miramemoria/app/services/neo4j_memory.py`; keeps `_run_query`, `_run_single`, `_get_driver`, `_ensure_constraints` helpers)
- `agent/persistence/bootstrap.py` (CUTIEE-specific constraints + indexes)
- `apps/accounts/neo4j_auth_backend.py` (ported from `miramemoria/app/services/neo4j_auth_backend.py`)
- `cutiee_site/neo4j_session_backend.py` (ported from `miramemoria/app/services/neo4j_session_backend.py`)
- `scripts/neo4j_up.sh` (one-shot dev-stack helper)

**Behavior:** `./scripts/neo4j_up.sh` starts the Docker container if not running, waits for the bolt port to open, calls `uv run python -m agent.persistence.bootstrap` to install CUTIEE's label namespace, and prints a ready banner. Idempotent — re-running the script is safe.

- [ ] **Step 1**: Write `docker-compose.yml`:

```yaml
services:
  neo4j:
    image: neo4j:5.24-community
    container_name: cutiee-neo4j
    restart: unless-stopped
    ports:
      - "7474:7474"   # HTTP browser UI
      - "7687:7687"   # Bolt protocol
    environment:
      NEO4J_AUTH: "neo4j/${NEO4J_PASSWORD:-cutiee-dev-password}"
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_dbms_security_procedures_unrestricted: "apoc.*"
      NEO4J_dbms_memory_heap_initial__size: "512m"
      NEO4J_dbms_memory_heap_max__size: "1G"
    volumes:
      - ./data/neo4j/data:/data
      - ./data/neo4j/logs:/logs
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:7474"]
      interval: 5s
      timeout: 3s
      retries: 10
```

- [ ] **Step 2**: Write `scripts/neo4j_up.sh` (chmod +x):

```bash
#!/usr/bin/env bash
set -euo pipefail
if [ -z "${CUTIEE_ENV:-}" ]; then source .env 2>/dev/null || true; fi
if [ "${CUTIEE_ENV:-}" != "local" ]; then
  echo "NEO4J_BOLT_URL points at AuraDB in production — no container to start." >&2
  exit 0
fi
mkdir -p data/neo4j/data data/neo4j/logs
docker compose up -d neo4j
echo "Waiting for bolt port 7687…"
for _ in $(seq 1 30); do
  if nc -z localhost 7687 2>/dev/null; then break; fi
  sleep 1
done
uv run python -m agent.persistence.bootstrap
echo "Neo4j ready at bolt://localhost:7687 (browser: http://localhost:7474)."
```

- [ ] **Step 3**: Port `neo4j_memory.py` → `agent/persistence/neo4j_client.py`. Keep the file's public surface almost identical to miramemoria's — `get_driver()`, `_run_query(cypher, **params)`, `_run_single(cypher, **params)`, `close_driver()`. Read credentials from `NEO4J_BOLT_URL`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`. Raise `RuntimeError` on missing env or unreachable host — no silent fallback.

- [ ] **Step 4**: Write `agent/persistence/bootstrap.py` that executes the constraint + index block documented in "Database Architecture — Neo4j as Default" (user_id, user_email, session_key, task_id, execution_id, step_id, template_id, fact_id, audit_id uniqueness; template_domain, template_stale, audit_user_time indexes). Use `IF NOT EXISTS` on every statement so the script is idempotent.

- [ ] **Step 5**: Port `neo4j_auth_backend.py` and `neo4j_session_backend.py` from miramemoria. Adjust the User node label namespace if miramemoria's is `User` — CUTIEE uses the same label. Confirm that the auth backend still exposes `authenticate(request, username, password)` and `get_user(user_id)` so Django picks it up, and that the session backend implements the full `SessionStore` interface (`create`, `exists`, `save`, `delete`, `load`, `clear_expired`).

- [ ] **Step 6**: Tests in `tests/agent/persistence/test_neo4j_client.py` and `tests/apps/accounts/test_neo4j_auth_backend.py`:

```python
# test_neo4j_client.py
import pytest
from agent.persistence.neo4j_client import _run_single, _run_query


@pytest.mark.local
def test_driver_roundtrip():
    _run_query("MATCH (n:_CUTIEE_SMOKE) DELETE n")
    _run_query("CREATE (:_CUTIEE_SMOKE {id: $id})", id = "smoke-1")
    row = _run_single("MATCH (n:_CUTIEE_SMOKE {id: $id}) RETURN n.id AS id", id = "smoke-1")
    assert row["id"] == "smoke-1"
    _run_query("MATCH (n:_CUTIEE_SMOKE) DELETE n")


def test_missing_env_raises(monkeypatch):
    from agent.persistence import neo4j_client
    monkeypatch.delenv("NEO4J_BOLT_URL", raising = False)
    monkeypatch.setattr(neo4j_client, "_driver", None, raising = False)
    with pytest.raises(RuntimeError, match = "NEO4J_BOLT_URL"):
        neo4j_client.get_driver()
```

```python
# test_neo4j_auth_backend.py
import pytest
from django.test import RequestFactory
from apps.accounts.neo4j_auth_backend import Neo4jAuthBackend


@pytest.mark.local
def test_authenticate_creates_and_returns_user():
    backend = Neo4jAuthBackend()
    user = backend.authenticate(RequestFactory().get("/"), username = "alice", password = "pw")
    assert user is None or user.username == "alice"  # Exact semantics depend on allauth flow
```

- [ ] **Step 7**: Update `.gitignore` to ignore `data/neo4j/`:

```gitignore
data/neo4j/
```

**Accept** when: `./scripts/neo4j_up.sh` exits 0, `cypher-shell -a bolt://localhost:7687 -u neo4j -p ... "SHOW CONSTRAINTS"` lists all CUTIEE constraints, and the smoke test `pytest -m local tests/agent/persistence/ -v` passes.

### Task 0.3: Django settings with `CUTIEE_ENV` switch

**File:** `cutiee_site/settings.py`

- [ ] **Step 1**: Update `settings.py` to read `django-environ`, add `INSTALLED_APPS` entries for `rest_framework`, `allauth`, `allauth.account`, `allauth.socialaccount`, `allauth.socialaccount.providers.google`, and the four `apps.*` apps. Configure `AUTH_USER_MODEL = "auth.User"`, `LOGIN_URL = "/auth/login/"`, `LOGIN_REDIRECT_URL = "/tasks/"`, `ACCOUNT_LOGIN_METHODS = {"email"}`, `TEMPLATES` with `DIRS = [BASE_DIR / "templates"]`. Wire **Neo4j as the default database** via the ported backends:

```python
# Django's internal tables (contenttypes, migrations, allauth schema) live in
# an in-memory sqlite — no on-disk file, no application data.
DATABASES = {
    "default": env.db("DJANGO_INTERNAL_DB_URL", default = "sqlite:///:memory:"),
}

# Domain + auth + sessions live in Neo4j.
NEO4J_BOLT_URL = env("NEO4J_BOLT_URL")
NEO4J_USERNAME = env("NEO4J_USERNAME")
NEO4J_PASSWORD = env("NEO4J_PASSWORD")
NEO4J_DATABASE = env("NEO4J_DATABASE", default = "neo4j")

AUTHENTICATION_BACKENDS = [
    "apps.accounts.neo4j_auth_backend.Neo4jAuthBackend",     # primary: Neo4j-backed users
    "allauth.account.auth_backends.AuthenticationBackend",   # django-allauth flow
]

SESSION_ENGINE = "cutiee_site.neo4j_session_backend"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 days
```

- [ ] **Step 2**: Configure `SOCIALACCOUNT_PROVIDERS` reading Google credentials from env:

```python
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": env("GOOGLE_CLIENT_ID"),
            "secret": env("GOOGLE_CLIENT_SECRET"),
            "key": "",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    },
}
SOCIALACCOUNT_LOGIN_ON_GET = True
SITE_ID = 1
```

- [ ] **Step 3**: At the top of `settings.py`, validate `CUTIEE_ENV` and all required env vars for each mode:

```python
import environ
env = environ.Env()
environ.Env.read_env()

CUTIEE_ENV = env("CUTIEE_ENV", default = None)
if CUTIEE_ENV not in {"local", "production"}:
    raise RuntimeError(
        "CUTIEE_ENV must be set to 'local' or 'production'. See .env.example."
    )

# Google OAuth is required in both envs (primary auth flow)
for required_key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    if not env(required_key, default = ""):
        raise RuntimeError(
            f"{required_key} is required. Google OAuth is the primary auth flow. "
            "Create credentials at https://console.cloud.google.com/apis/credentials."
        )

# Env-specific required keys
if CUTIEE_ENV == "production" and not env("GEMINI_API_KEY", default = ""):
    raise RuntimeError("GEMINI_API_KEY required when CUTIEE_ENV=production.")
if CUTIEE_ENV == "local" and not env("QWEN_SERVER_URL", default = ""):
    raise RuntimeError("QWEN_SERVER_URL required when CUTIEE_ENV=local.")

# Neo4j is required in both envs — it is the default database.
for required_key in ("NEO4J_BOLT_URL", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
    if not env(required_key, default = ""):
        raise RuntimeError(
            f"{required_key} is required. Neo4j is the default database. "
            "Start it locally via `./scripts/neo4j_up.sh`, or set AuraDB credentials "
            "for production."
        )
```

- [ ] **Step 4**: Run `uv run python manage.py migrate` so the Django-framework tables (`contenttypes`, `admin`, `sites`, `auth`, `allauth`) exist inside the in-memory sqlite on startup. Because the sqlite URL is `:memory:`, this step re-runs automatically on every process start — no on-disk migration state to manage. All application data is in Neo4j, bootstrapped separately via `uv run python -m agent.persistence.bootstrap`. Update the default `Site` object (`SITE_ID = 1`) at startup via a Django `AppConfig.ready()` hook inside `apps/accounts/apps.py`.

- [ ] **Step 3**: Stub the four Django apps:

```bash
mkdir apps
cd apps
for APP in accounts tasks memory_app audit; do
  uv run django-admin startapp "$APP"
done
cd ..
```

Add `__init__.py` in `apps/` and register each as `apps.<name>` in `INSTALLED_APPS`.

### Task 0.4: Agent package scaffold + miramemoria design inheritance

**Files:**
- `agent/__init__.py` and empty `__init__.py` for each subdirectory
- `static/css/base.css` (copied from miramemoria, brand-renamed)
- `static/css/main.css`
- `static/css/tailwind.input.css`
- `templates/base.html`

- [ ] **Step 1**: Create empty `__init__.py` files for every `agent/*` subdirectory listed in the Project Structure.

- [ ] **Step 2**: Copy miramemoria's base styles:

```bash
cp /Users/edwardhu/Desktop/INFO490/miramemoria/static/css/base.css static/css/base.css
cp /Users/edwardhu/Desktop/INFO490/miramemoria/static/css/main.css static/css/main.css
cp /Users/edwardhu/Desktop/INFO490/miramemoria/static/css/tailwind.input.css static/css/tailwind.input.css
cp /Users/edwardhu/Desktop/INFO490/miramemoria/static/css/tailwind.built.css static/css/tailwind.built.css
cp /Users/edwardhu/Desktop/INFO490/miramemoria/static/css/mobile-patterns.css static/css/mobile-patterns.css
```

- [ ] **Step 3**: Find-replace any Memoria-specific class names in the copied CSS (`mm-*` Tailwind aliases stay as-is for brand continuity, but verify no `url("/static/images/logo.png")` references point to assets we do not have; add placeholder images at `static/images/`).

- [ ] **Step 4**: Write `templates/base.html` matching miramemoria's structure. Replace "Memoria" branding with "CUTIEE" in the header, keep the Inter + Manrope Google Fonts link, the glass-morphism header, and the `--primary-blue: #6C86C0` design tokens. Keep `{% block content %}`. Simplify by removing Pusher/driver.js tour code for now (add back later if needed).

```html
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>{% block title %}CUTIEE{% endblock %}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{% static 'css/tailwind.built.css' %}?v={% now 'U' %}">
    <link rel="stylesheet" href="{% static 'css/base.css' %}?v={% now 'U' %}">
    <link rel="stylesheet" href="{% static 'css/main.css' %}?v={% now 'U' %}">
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    {% block extra_css %}{% endblock %}
</head>
<body class="h-screen overflow-hidden{% if user.is_authenticated %} has-bottom-nav{% endif %}">
    <div class="flex flex-col h-screen w-screen overflow-hidden">
        <header id="app-header" class="h-[64px] w-full flex-shrink-0">
            <div class="flex items-center justify-between h-full px-8">
                <a href="{% url 'tasks:list' %}" class="font-manrope font-extrabold text-mm-primary text-[20px] tracking-[-1px]">CUTIEE</a>
                <div class="flex items-center gap-3">
                    {% if user.is_authenticated %}
                        <a href="{% url 'memory_app:list' %}" class="header-icon-btn">Memory</a>
                        <a href="{% url 'audit:list' %}" class="header-icon-btn">Audit</a>
                        <form method="post" action="{% url 'accounts:logout' %}" style="display:inline">{% csrf_token %}<button type="submit" class="btn-ghost">Log out</button></form>
                    {% else %}
                        <a href="{% url 'accounts:login' %}" class="btn-gradient px-4 py-2">Log in</a>
                    {% endif %}
                </div>
            </div>
        </header>
        <main id="main-content" class="flex-1 overflow-auto backdrop-blur-[20px] bg-white/20">
            {% block content %}{% endblock %}
        </main>
    </div>
    {% block extra_js %}{% endblock %}
</body>
</html>
```

### Task 0.5: Qwen download, llama-server, and the background-loading `dev.sh`

**Files:**
- `scripts/download_qwen.py`
- `scripts/start_llama_server.sh` (chmod +x)
- `scripts/dev.sh` (chmod +x) — single entry point for local dev

**Behavior:** The GGUF is cached in `data/models/qwen/*.gguf` after first download (`.gitignore` excludes `data/`). The `dev.sh` script verifies the cache, launches llama-server in the background (warm-up takes ~5-10s from cache once downloaded), and starts Django in the foreground immediately. The Django app serves right away while the VLM warms up; the UI polls `/api/vlm-health/` and displays a "Warming up Qwen3.5 0.8B…" banner until the model is ready.

- [ ] **Step 1**: Write `scripts/download_qwen.py`:

```python
"""Download Qwen3.5 0.8B Q4_K_M GGUF.

Errors out if QWEN_MODEL_ID or QWEN_GGUF_FILENAME are unset.
No fallback to any other model size.
"""
import os
import sys
from pathlib import Path
from huggingface_hub import hf_hub_download

MODEL_DIR = Path(os.environ.get("CUTIEE_MODEL_DIR", "./data/models"))
REPO_ID = os.environ.get("QWEN_MODEL_ID")
FILENAME = os.environ.get("QWEN_GGUF_FILENAME")


def main() -> None:
    if not REPO_ID or not FILENAME:
        print(
            "ERROR: QWEN_MODEL_ID and QWEN_GGUF_FILENAME must be set. "
            "See .env.example.",
            file = sys.stderr,
        )
        sys.exit(1)
    target = MODEL_DIR / "qwen"
    target.mkdir(parents = True, exist_ok = True)
    path = hf_hub_download(repo_id = REPO_ID, filename = FILENAME, local_dir = str(target))
    print(f"Downloaded: {path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2**: Write `scripts/start_llama_server.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${CUTIEE_MODEL_DIR:-./data/models}"
FILENAME="${QWEN_GGUF_FILENAME:-qwen3.5-0.8b-instruct-q4_k_m.gguf}"
MODEL_PATH="$MODEL_DIR/qwen/$FILENAME"

if [ ! -f "$MODEL_PATH" ]; then
  echo "ERROR: Model not found at $MODEL_PATH" >&2
  echo "Run: python scripts/download_qwen.py" >&2
  exit 1
fi

if ! command -v llama-server &> /dev/null; then
  echo "ERROR: llama-server binary not on PATH" >&2
  echo "  macOS:  brew install llama.cpp" >&2
  echo "  Linux:  build from https://github.com/ggml-org/llama.cpp" >&2
  exit 1
fi

llama-server \
  -m "$MODEL_PATH" \
  --host 0.0.0.0 --port 8001 \
  --ctx-size 8192 \
  --threads 8 \
  --logprobs 10
```

- [ ] **Step 3**: Write `scripts/dev.sh` — the single command developers run:

```bash
#!/usr/bin/env bash
# Start the full local dev stack: llama-server (background) + Django (foreground).
# Django starts immediately; the VLM warms up in parallel.
# The UI polls /api/vlm-health/ to know when Qwen is ready and enables the task form.

set -euo pipefail

if [ -z "${CUTIEE_ENV:-}" ]; then
  source .env 2>/dev/null || true
fi

if [ "${CUTIEE_ENV:-}" != "local" ]; then
  echo "ERROR: CUTIEE_ENV must be 'local' for dev.sh (got: ${CUTIEE_ENV:-unset})" >&2
  exit 1
fi

MODEL_DIR="${CUTIEE_MODEL_DIR:-./data/models}"
FILENAME="${QWEN_GGUF_FILENAME:-qwen3.5-0.8b-instruct-q4_k_m.gguf}"
MODEL_PATH="$MODEL_DIR/qwen/$FILENAME"

if [ ! -f "$MODEL_PATH" ]; then
  echo "Qwen GGUF not cached. Downloading (~500MB, one-time)…"
  uv run python scripts/download_qwen.py
fi

mkdir -p data/audit_logs

echo "Starting llama-server in background on :8001 (warm-up ~5-10s from cache)…"
./scripts/start_llama_server.sh > data/audit_logs/llama.log 2>&1 &
LLAMA_PID=$!

cleanup() {
  echo ""
  echo "Stopping llama-server (PID $LLAMA_PID)…"
  kill "$LLAMA_PID" 2>/dev/null || true
  wait "$LLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting Django on :8000…"
echo "  UI will show 'Warming up…' until Qwen responds at :8001/health"
uv run python manage.py runserver
```

- [ ] **Step 4**: Add the VLM health endpoint `GET /api/vlm-health/` in `apps/tasks/api.py`:

```python
"""Report whether the local VLM or production API is ready to serve requests."""
import os
import httpx
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def vlm_health(request):
    env = os.environ.get("CUTIEE_ENV", "")
    if env == "production":
        return JsonResponse({"status": "ready", "env": "production", "model": "gemini-3.1"})
    if env == "local":
        url = os.environ.get("QWEN_SERVER_URL", "http://localhost:8001")
        try:
            with httpx.Client(timeout = 1.0) as client:
                resp = client.get(f"{url}/health")
            if resp.status_code == 200:
                return JsonResponse({"status": "ready", "env": "local", "model": "qwen3.5-0.8b"})
            return JsonResponse({"status": "loading", "env": "local", "model": "qwen3.5-0.8b"})
        except (httpx.ConnectError, httpx.TimeoutException):
            return JsonResponse({"status": "loading", "env": "local", "model": "qwen3.5-0.8b"})
    return JsonResponse({"status": "unavailable", "env": env}, status = 503)
```

Register in `cutiee_site/urls.py` root: `path("api/vlm-health/", vlm_health, name = "vlm_health")`.

- [ ] **Step 5**: Add a readiness banner to `templates/base.html` inside `<body>` above `<main>`:

```html
<div id="vlm-status-banner" class="glass-surface glass-surface--tinted hidden px-4 py-2 text-sm text-mm-text"
     hx-get="{% url 'vlm_health' %}"
     hx-trigger="load, every 2s"
     hx-swap="outerHTML"
     hx-target="this">
  Checking model status…
</div>
```

Server-side, `vlm_health` returns a partial HTML block (not JSON) when the request includes `HX-Request: true`:
- `status=loading` → banner visible, text "Warming up Qwen3.5 0.8B…", form disabled via CSS attribute
- `status=ready` → banner replaced with empty div; `<body>` class toggled to enable submit buttons
- `status=unavailable` → red error banner

Adjust `vlm_health` to detect `HX-Request` and branch between JSON and HTML responses. Task-submit forms include `:disabled="!vlmReady"` (via a tiny vanilla JS listener on the banner replacement event) so users cannot submit tasks before Qwen is ready.

- [ ] **Step 6**: Document the dev workflow in README: "Run `./scripts/dev.sh`. Django comes up at :8000 immediately; the Qwen model warms up in the background. The UI disables task submission until the model is ready (typically ~5-10 seconds after first start, faster on subsequent starts because the GGUF is cached)."

### Task 0.6: Render deployment config

**File:** `render.yaml`

- [ ] **Step 1**: Write `render.yaml`:

```yaml
services:
  - type: web
    name: cutiee
    env: python
    region: oregon
    plan: starter
    buildCommand: "uv sync && uv run python manage.py collectstatic --no-input && uv run python -m agent.persistence.bootstrap"
    startCommand: "uv run gunicorn cutiee_site.wsgi --bind 0.0.0.0:$PORT"
    # Django's in-memory sqlite migrates at process start (no persistent state).
    # Neo4j constraints are idempotent — bootstrap runs safely on every deploy.
    envVars:
      - key: CUTIEE_ENV
        value: production
      - key: DJANGO_SECRET_KEY
        generateValue: true
      - key: DJANGO_DEBUG
        value: "False"
      - key: DJANGO_ALLOWED_HOSTS
        value: "cutiee.onrender.com"
      - key: GEMINI_API_KEY
        sync: false  # Set manually in Render dashboard
      - key: GEMINI_MODEL_TIER1
        value: "gemini-3.1-flash-lite"
      - key: GEMINI_MODEL_TIER2
        value: "gemini-3.1-flash"
      - key: GEMINI_MODEL_TIER3
        value: "gemini-3.1-pro"
      - key: GOOGLE_CLIENT_ID
        sync: false  # Set manually in Render dashboard (required for auth)
      - key: GOOGLE_CLIENT_SECRET
        sync: false  # Set manually in Render dashboard (required for auth)
      - key: NEO4J_BOLT_URL
        sync: false  # AuraDB Free: neo4j+s://<dbid>.databases.neo4j.io
      - key: NEO4J_USERNAME
        sync: false  # AuraDB generated username (usually "neo4j")
      - key: NEO4J_PASSWORD
        sync: false  # AuraDB generated password (shown once on instance creation)
      - key: NEO4J_DATABASE
        value: "neo4j"
      - key: DJANGO_INTERNAL_DB_URL
        value: "sqlite:///:memory:"
      - key: CUTIEE_RECENCY_WINDOW
        value: "3"
      - key: CUTIEE_TEMPLATE_MATCH_THRESHOLD
        value: "0.85"
      - key: CUTIEE_CONFIDENCE_THRESHOLD_TIER1
        value: "0.75"
      - key: CUTIEE_CONFIDENCE_THRESHOLD_TIER2
        value: "0.65"
      - key: CUTIEE_CONFIDENCE_THRESHOLD_TIER3
        value: "0.50"
      - key: PYTHON_VERSION
        value: "3.11.9"
```

### Task 0.7: Phase 0 verification tests

**File:** `tests/test_phase0_setup.py`

- [ ] **Step 1**: Write tests:

```python
"""Verify Phase 0 setup."""
import os
import sys
import httpx
import pytest
from pathlib import Path


def test_python_version():
    assert sys.version_info >= (3, 11)


def test_dependencies_importable():
    import django  # noqa: F401
    import rest_framework  # noqa: F401
    import playwright  # noqa: F401
    import llama_cpp  # noqa: F401
    from google import genai  # noqa: F401
    import neo4j  # noqa: F401
    import fastembed  # noqa: F401


def test_django_settings_require_cutiee_env(monkeypatch):
    monkeypatch.delenv("CUTIEE_ENV", raising = False)
    with pytest.raises(RuntimeError, match = "CUTIEE_ENV"):
        import importlib
        import cutiee_site.settings
        importlib.reload(cutiee_site.settings)


def test_data_dir_structure():
    data_dir = Path(os.environ.get("CUTIEE_DATA_DIR", "./data"))
    data_dir.mkdir(parents = True, exist_ok = True)
    (data_dir / "models").mkdir(exist_ok = True)
    (data_dir / "audit_logs").mkdir(exist_ok = True)
    assert data_dir.exists()


@pytest.mark.local
def test_qwen_gguf_downloaded():
    model_dir = Path(os.environ.get("CUTIEE_MODEL_DIR", "./data/models"))
    assert list((model_dir / "qwen").glob("*.gguf")), "Run python scripts/download_qwen.py"


@pytest.mark.local
async def test_qwen_server_reachable():
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8001/health", timeout = 5)
        assert resp.status_code == 200


@pytest.mark.production
def test_gemini_api_key_set():
    assert os.environ.get("GEMINI_API_KEY"), \
        "GEMINI_API_KEY required when CUTIEE_ENV=production"
```

### Task 0.8: First Django migration

- [ ] **Step 1**: Run:

```bash
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
# Open http://localhost:8000/admin/
```

### Phase 0 Acceptance

- [ ] Directory renamed `CUITEEE` → `CUTIEE`, git initialized, remote added
- [ ] `uv sync` clean
- [ ] `uv run playwright install chromium` clean
- [ ] `python scripts/download_qwen.py` downloads the GGUF
- [ ] `uv run pytest tests/test_phase0_setup.py` passes non-local / non-production tests
- [ ] `uv run python manage.py runserver` serves the Django welcome + admin
- [ ] `docs/part1_product_refinement.md` drafted
- [ ] `render.yaml` committed

### Phase 0 Checkpoint

User commits the scaffold and pushes to `origin main`.

---

# Phase 1 — Core Harness, Browser Layer, Django Models (Week 1)

**Goal:** Minimal observe-reason-act agent loop driven by a mock VLM, plus Cypher-backed repos for persistence. No memory, pruning, or routing yet.

### Task 1.1: Agent state dataclasses

**File:** `agent/harness/state.py`, `tests/agent/harness/test_state.py`

- [ ] **Step 1**: Test-first for `Action`, `ObservationStep`, `AgentState` defaults.
- [ ] **Step 2**: Implement dataclasses (`Action`, `ObservationStep`, `AgentState`, `ActionType` enum, `RiskLevel` enum). See the original CUITEEE spec Section 5.2 for field details; keep identical structure, update the name.
- [ ] **Step 3**: Run. PASS.

### Task 1.2: Agent configuration

**File:** `agent/harness/config.py`, `tests/agent/harness/test_config.py`

- [ ] **Step 1**: Test-first: reads `CUTIEE_ENV`, `CUTIEE_RECENCY_WINDOW`, three thresholds.
- [ ] **Step 2**: Implement `Config.from_env()` — raises `RuntimeError` when `CUTIEE_ENV` is missing; raises when `CUTIEE_ENV=local` but no Qwen server URL; raises when `CUTIEE_ENV=production` but no `GEMINI_API_KEY`.
- [ ] **Step 3**: Run. PASS including all three error paths.

### Task 1.3: Browser controller + DOM extractor

**Files:** `agent/browser/controller.py`, `agent/browser/dom_extractor.py`, matching tests.

- [ ] **Step 1**: Implement `BrowserController` (lifecycle, action execution via Playwright) and `extract_dom_state(page)` producing compact markdown. Follow the original CUITEEE spec (Section 5.2) verbatim, adjusted for the new package path.
- [ ] **Step 2**: Tests cover browser lifecycle, navigate/click/fill actions, graceful failure, DOM extraction (<200 tokens on simple pages), hidden element filtering.

### Task 1.4: Mock VLM client

**File:** `agent/routing/models/mock.py`

- [ ] **Step 1**: Implement `MockVLMClient` with `actions_to_return`, `last_pruned_context`, returning `(action, confidence, cost)`.

### Task 1.5: Phase-1 orchestrator

**File:** `agent/harness/orchestrator.py`, `tests/agent/harness/test_orchestrator.py`

- [ ] **Step 1**: Test-first: finish completes, sequence executes, failed action aborts.
- [ ] **Step 2**: Implement minimal `Orchestrator` with `run_task(task_description) -> AgentState`.

### Task 1.6: Neo4j-backed domain repositories (Task / Execution / Step / ProceduralTemplate / MemoryBullet / AuditEntry)

**Files:**
- `apps/tasks/repo.py`            (`TaskRepo`, `ExecutionRepo`, `StepRepo`)
- `apps/memory_app/repo.py`       (`TemplateRepo`, `MemoryBulletRepo`)
- `apps/memory_app/bullet.py`     (the `Bullet` and `DeltaUpdate` dataclasses — ported from `LongTermMemoryBasedSelfEvolvingAlgorithm/src/ace_memory.py`, lines 45-191)
- `apps/audit/repo.py`            (`AuditRepo`)

Because Neo4j is the default database and Django ORM is bypassed, these are thin Cypher-backed repository modules, not ORM models. Each repo exposes idiomatic Python functions (`create`, `get`, `list_for_user`, `update`, `delete`) that call into `agent.persistence.neo4j_client._run_query` / `_run_single`.

**Bullet schema (ported verbatim from LongTermMemoryBasedSelfEvolvingAlgorithm):**

```python
# apps/memory_app/bullet.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class Bullet:
    id: str
    content: str
    memory_type: str                    # "semantic" | "episodic" | "procedural"
    tags: list[str] = field(default_factory = list)
    topic: str = ""
    concept: str = ""
    content_hash: str = ""
    context_scope_id: str = ""
    learner_id: str = ""
    helpful_count: int = 0
    harmful_count: int = 0
    semantic_strength: float = 0.0
    episodic_strength: float = 0.0
    procedural_strength: float = 0.0
    semantic_access_index: int = 0
    episodic_access_index: int = 0
    procedural_access_index: int = 0
    semantic_last_access: datetime | None = None
    episodic_last_access: datetime | None = None
    procedural_last_access: datetime | None = None
    ttl_days: int | None = None
    embedding: list[float] | None = None
    created_at: datetime = field(default_factory = datetime.utcnow)
    last_used: datetime = field(default_factory = datetime.utcnow)

@dataclass
class DeltaUpdate:
    new_bullets: list[Bullet] = field(default_factory = list)
    update_bullets: dict[str, dict[str, Any]] = field(default_factory = dict)
    remove_bullets: list[str] = field(default_factory = list)
    metadata: dict[str, Any] = field(default_factory = dict)
```

**Representative repo function:**

```python
# apps/memory_app/repo.py
from agent.persistence.neo4j_client import _run_query, _run_single
from apps.memory_app.bullet import Bullet, DeltaUpdate

def upsert_bullet(user_id: str, bullet: Bullet) -> None:
    _run_query(
        """
        MERGE (u:User {id: $user_id})
        MERGE (b:MemoryBullet {id: $id})
        SET b.content = $content,
            b.memory_type = $memory_type,
            b.tags = $tags,
            b.content_hash = $content_hash,
            b.helpful_count = $helpful_count,
            b.harmful_count = $harmful_count,
            b.semantic_strength = $semantic_strength,
            b.episodic_strength = $episodic_strength,
            b.procedural_strength = $procedural_strength,
            b.semantic_access_index = $semantic_access_index,
            b.episodic_access_index = $episodic_access_index,
            b.procedural_access_index = $procedural_access_index,
            b.embedding = $embedding,
            b.ttl_days = $ttl_days,
            b.last_used = $last_used
        MERGE (u)-[:HOLDS]->(b)
        """,
        user_id = user_id,
        id = bullet.id,
        content = bullet.content,
        memory_type = bullet.memory_type,
        tags = bullet.tags,
        content_hash = bullet.content_hash,
        helpful_count = bullet.helpful_count,
        harmful_count = bullet.harmful_count,
        semantic_strength = bullet.semantic_strength,
        episodic_strength = bullet.episodic_strength,
        procedural_strength = bullet.procedural_strength,
        semantic_access_index = bullet.semantic_access_index,
        episodic_access_index = bullet.episodic_access_index,
        procedural_access_index = bullet.procedural_access_index,
        embedding = bullet.embedding,
        ttl_days = bullet.ttl_days,
        last_used = bullet.last_used.isoformat(),
    )
```

- [ ] **Step 1**: Write `Bullet` and `DeltaUpdate` dataclasses verbatim from reference source.
- [ ] **Step 2**: Write Cypher-backed repos for each entity; each repo function takes `user_id` as its first argument to enforce per-user scoping at the query level (no cross-tenant leaks).
- [ ] **Step 3**: Round-trip tests (`@pytest.mark.local`) that upsert an entity, re-read it, and assert equality. Also assert that deleting a `User` cascades to `Task`, `Execution`, `Step`, `MemoryBullet`, and `AuditEntry` via a `DETACH DELETE` sweep.

### Task 1.7: Phase-1 smoke test

**File:** `tests/integration/test_phase1_smoke.py`

- [ ] **Step 1**: End-to-end: create a `Task` via `TaskRepo.create`, run the orchestrator with a mock client, persist the `Execution` and `Step`s via `ExecutionRepo.create` + `StepRepo.append`, assert `MATCH (t:Task {id: $tid})-[:EXECUTED_AS]->(e)-[:HAS_STEP]->(s) RETURN count(s)` equals the expected step count.

### Phase 1 Acceptance

- [ ] `uv run pytest tests/agent/ tests/apps/ tests/integration/test_phase1_smoke.py -v`
- [ ] Browser controller lifecycle green
- [ ] DOM extractor keeps <2000 tokens
- [ ] Django migrations apply; models round-trip
- [ ] Mock orchestrator completes scripted tasks

### === PHASE 1 REVIEW CHECKPOINT (MANDATORY PER USER REQUEST) ===

**Stop here.** Run:

```bash
uv run pytest -m "not slow and not local and not production and not integration" -v
uv run pytest tests/integration/test_phase1_smoke.py -v
```

Summarize test counts, migration status, skipped tests. Ask "proceed to Phase 2?"

---

# Phase 2 — ACE Memory: Three-Strength Bullets, Reflect→Curate→Apply, Procedural Replay (Week 2)

**Goal:** Mechanism 1 — a unified memory subsystem that (a) represents every piece of remembered knowledge as a three-strength `Bullet` (semantic / episodic / procedural channels), (b) extracts bullets from successful traces via a `Reflector → Quality Gate → Curator → apply_delta` loop, (c) replays procedural-type bullets at zero inference cost when they match the current task above threshold, and (d) self-evolves: failed steps re-ground through the router and the template mutates via `DeltaUpdate.update_bullets`.

**Source lineage:** The `Bullet` / `DeltaUpdate` schema and the decay math come verbatim from `/Users/edwardhu/Desktop/INFO490/LongTermMemoryBasedSelfEvolvingAlgorithm/src/ace_memory.py` (lines 45–191 for dataclasses; 743–850 for retrieval). The Neo4j Cypher layer comes from `/Users/edwardhu/Desktop/INFO490/miramemoria/app/services/neo4j_memory.py` and `app/chat/ace_runtime.py` (lines 387–821). We combine the research-grade dataclass interface with the production-grade Cypher.

### Task 2.1: Port the Bullet / DeltaUpdate schema + decay math

**Files:**
- `apps/memory_app/bullet.py` (dataclasses — already scaffolded in Task 1.6)
- `agent/memory/decay.py` (per-channel exponential decay — ported from miramemoria `app/chat/decay.py`, lines 1–35)
- `tests/agent/memory/test_bullet.py`, `tests/agent/memory/test_decay.py`

Decay constants live in one module so they are easy to audit in the Technical Report:

```python
# agent/memory/decay.py
SEMANTIC_DECAY_RATE = 0.01      # slow — factual knowledge
EPISODIC_DECAY_RATE = 0.05      # fast — specific events fade
PROCEDURAL_DECAY_RATE = 0.002   # near-zero — workflows persist

def decayed_strength(strength: float, access_delta: int, rate: float) -> float:
    """Exponential decay: strength * exp(-rate * (access_clock - last_access_index))."""
    import math
    return strength * math.exp(-rate * max(access_delta, 0))

def total_strength(bullet) -> float:
    """Sum of three decayed channel strengths — used in retrieval ranking."""
    return (
        decayed_strength(bullet.semantic_strength, bullet.current_clock - bullet.semantic_access_index, SEMANTIC_DECAY_RATE)
        + decayed_strength(bullet.episodic_strength, bullet.current_clock - bullet.episodic_access_index, EPISODIC_DECAY_RATE)
        + decayed_strength(bullet.procedural_strength, bullet.current_clock - bullet.procedural_access_index, PROCEDURAL_DECAY_RATE)
    )
```

- [ ] Tests cover (a) freshly created bullet has full strength, (b) decay math collapses to the exponential identity for zero time delta, (c) decay rate ordering holds: semantic fades faster than procedural over 1000 access ticks.

### Task 2.2: ACEMemory — retrieve, rank, prune

**Files:** `agent/memory/ace_memory.py`, `tests/agent/memory/test_ace_memory.py`

Ported from `LongTermMemoryBasedSelfEvolvingAlgorithm/src/ace_memory.py` (retrieval lines 743–850) but persistence goes through `apps/memory_app/repo.py` into Neo4j.

Public interface:

```python
class ACEMemory:
    def __init__(self, user_id: str, max_bullets: int = 100): ...
    def retrieve_relevant_bullets(
        self,
        query: str,
        k: int = 8,
        facets: dict | None = None,
    ) -> list[Bullet]: ...
    def apply_delta(self, delta: DeltaUpdate) -> None: ...
    def advance_clock(self) -> None: ...
    def refine(self) -> None:           # dedup + prune
    def as_prompt_block(self, bullets: list[Bullet]) -> str: ...
```

**Ranking formula** (identical to the reference implementation):

```
score = 0.60 * relevance(query, bullet.content, bullet.embedding)
      + 0.20 * normalized_total_strength(bullet)
      + 0.20 * type_priority(bullet.memory_type)         # procedural 1.0 > episodic 0.7 > semantic 0.4
      + 0.08 if bullet is learned (non-meta-strategy)
      - 0.25 if bullet is a seed
      + 0.20 if facet match: needs_visual
      + 0.10 if facet match: persona_request
```

with a hard post-filter: if top-k contains fewer than 2 learned bullets, swap in learned bullets from the next tier.

**Refine step** (dedup + prune, lines 494–678 of `ace_components.py`):
- Dedup: embedding cosine similarity ≥ 0.85 OR text Jaccard ≥ 0.75 → keep the bullet with the higher `helpful_count`, delete the other.
- Prune: if `len(bullets) > max_bullets`, delete the `len - max_bullets` lowest-scoring bullets (score = `total_strength + 0.1 * helpful_count`).

- [ ] **Step 1**: Test retrieve returns at least 2 learned bullets when they exist; test apply_delta inserts new bullets and increments helpful_count on `update_bullets`; test refine deletes duplicates and caps size at max_bullets.
- [ ] **Step 2**: Implement the public interface. `retrieve_relevant_bullets` advances `access_clock` and updates `*_access_index` for each returned bullet so decay curves stay in sync with real usage.

### Task 2.3: Reflector → Quality Gate → Curator pipeline

**Files:**
- `agent/memory/reflector.py`       (ported from `ace_components.py` lines 305–355)
- `agent/memory/quality_gate.py`    (ported from `ace_components.py` lines 163–293)
- `agent/memory/curator.py`         (ported from `ace_components.py` lines 494–678)
- `agent/memory/pipeline.py`        (orchestrates the three stages — `ACEPipeline.process_execution`)
- `tests/agent/memory/test_pipeline.py`

**Flow** (the self-evolving spine):

```
execution_trace
   │
   ▼
Reflector.reflect(trace) ──► [LessonCandidate, ...]
                                   │
                                   ▼
                  QualityGate.apply(candidates, trace)
                                   │
     ┌─────────────── gate_score ≥ 0.60 ───────────────┐
     │                                                 │
     ▼                                                 ▼
  reject (record diagnostics)           Curator.curate(accepted) ──► DeltaUpdate
                                                                           │
                                                                           ▼
                                                             memory.apply_delta(delta)
                                                                           │
                                                                           ▼
                                                             memory.refine()   # dedup + prune
```

**Quality gate formula:**

```
gate_score = 0.35 * output_valid + 0.35 * avg_lesson_quality + 0.30 * avg_confidence
```

Accept when `gate_score ≥ 0.60` AND the reflector returned at least one lesson with `confidence ≥ 0.70` AND overlap-between-lessons ≥ 0.05 (lessons aren't all identical).

**Curator** converts accepted lessons into a `DeltaUpdate`:
- New lesson → `new_bullets` entry. `memory_type` set from the reflector's hint, falling back to a heuristic (`procedural` if the content contains "step|procedure|workflow", `episodic` if it contains "user|prefers|asked", else `semantic`).
- Lesson matches an existing bullet (embedding cosine ≥ 0.90) → `update_bullets[id]` with `helpful += 1`.
- Lesson contradicts an existing bullet (reflector emits `remove_id`) → `remove_bullets.append(id)`.

- [ ] **Step 1**: Mock-VLM test: reflector parses a canned trace and returns three lessons. Quality gate accepts, curator produces a delta with two new bullets and one update, memory apply_delta + refine runs without error.
- [ ] **Step 2**: Failure-case tests: gate rejects when output_valid=0, rejects when avg_confidence < 0.70, rejects when all lessons are identical (overlap too low).

### Task 2.4: Procedural replay — extract procedural bullets from traces and replay them

**Files:** `agent/memory/replay.py`, `tests/agent/memory/test_replay.py`

The replay executor is now a **consumer** of procedural-type bullets rather than a separate template store. On a successful task, the reflector emits one structured procedural bullet per step:

```json
{
  "memory_type": "procedural",
  "content": "step_index=3 action=fill target=input[name='email'] value=$USER_EMAIL",
  "tags": ["task:login", "domain:example.com"],
  "topic": "login-example.com",
  "concept": "email-field-fill"
}
```

Replay matches the current task via `ACEMemory.retrieve_relevant_bullets(task_description, facets={"need_procedural": True})` filtered to `memory_type == "procedural"` and clustered by `topic`. The cluster is rebuilt into a `ReplayPlan` (ordered list of actions) and executed. On step-level verification failure, the replay invokes `recovery_callback(failed_bullet)` which (a) re-grounds via the router, (b) emits a new procedural bullet with higher confidence, and (c) returns a `DeltaUpdate{update_bullets: {failed_bullet.id: {harmful: +1, procedural_strength: -10}}, new_bullets: [replacement]}` which `memory.apply_delta` persists immediately.

- [ ] **Step 1**: Replay happy-path test: two identical tasks, second hits replay with `total_cost_usd == 0`.
- [ ] **Step 2**: Self-healing test: mutate a selector between runs; second run triggers `recovery_callback`, delta update applies, third run replays cleanly.
- [ ] **Step 3**: Approval-gate test: procedural bullet tagged `risk:high` suspends execution and waits for user approval before executing the step.

### Task 2.5: SemanticFact — credential namespace

**Files:** `agent/memory/semantic.py`, `tests/agent/memory/test_semantic.py`

Credentials (passwords, tokens) are persisted as a **restricted subset of bullets** with `memory_type="semantic"`, `tags` containing `credential:<domain>`, and `content` encrypted at rest via `cryptography.fernet`. The retrieval path refuses to include credential bullets in any prompt-bound context block — they are only surfaced on explicit `get_credential(domain)` calls inside the replay executor's variable resolver.

- [ ] **Step 1**: Encryption round-trip test.
- [ ] **Step 2**: Assertion test: `as_prompt_block` never emits a credential bullet, even if it scores highest.

### Task 2.6: Wire ACEMemory into the orchestrator

**File:** modify `agent/harness/orchestrator.py`, `tests/agent/harness/test_orchestrator_with_memory.py`

- [ ] **Step 1**: After every completed run, orchestrator calls `pipeline.process_execution(trace)` to invoke the Reflect→Gate→Curate→Apply cycle.
- [ ] **Step 2**: Before every new run, orchestrator calls `memory.retrieve_relevant_bullets(task)` and passes the resulting bullets into the prompt builder as a "prior knowledge" block (procedural bullets become the replay candidate set; semantic and episodic bullets become context hints for tier selection).

### Phase 2 Acceptance

- [ ] `Bullet` / `DeltaUpdate` round-trip through Neo4j via `apps/memory_app/repo.py`
- [ ] Three-strength decay curves monotonically decrease; semantic fades faster than procedural
- [ ] Quality gate rejects low-confidence lessons and records diagnostics
- [ ] Curator produces a sensible delta (new bullets + updates on duplicates)
- [ ] Retrieval returns at least 2 learned bullets when the store contains them
- [ ] Procedural replay executes at zero inference cost on the second identical task
- [ ] Self-healing updates a failing bullet via `DeltaUpdate` and the third run replays cleanly
- [ ] Credentials never leak into prompt context blocks

---

# Phase 3 — Temporal Recency Pruning, ACE Access-Clock, Context Budgeting (Week 3)

**Goal:** Mechanism 2 — keep both the per-task trajectory context and the cross-task ACE bullet store bounded. The task-level `RecencyPruner` uses an N=3 sliding window with graduated compression. The memory-level bound uses the ACE access-clock plus per-channel decay — every retrieval advances the clock, every absent channel decays, and `ACEMemory.refine()` prunes when `len(bullets) > max_bullets`. The two pruning surfaces share a single `budget_allocator` that partitions the remaining context tokens between "fresh trajectory" and "retrieved ACE bullets" based on task recency and tier escalation.

### Task 3.1: RecencyPruner (trajectory-level)

**File:** `agent/pruning/context_window.py`, tests

- [ ] **Step 1**: 5 tests: empty, small, medium, large zone partitioning, ≥70% reduction on 15-step histories.
- [ ] **Step 2**: Implement `PrunedContext` + `RecencyPruner(recency_window = 3)` with `prune(history)` and `format_for_prompt(pruned)`. Recent N=3 steps are kept verbatim; intermediate steps are compressed to a one-line summary; distant steps are merged into a rule-based aggregate.

### Task 3.1b: ACE access-clock advancement

**File:** modify `agent/memory/ace_memory.py`, add `tests/agent/memory/test_access_clock.py`

- [ ] **Step 1**: Every call to `retrieve_relevant_bullets` increments a monotonic `access_clock` on the owning `(:Memory)` node. For each bullet returned in top-k, set `<channel>_access_index = access_clock` for the channel whose strength contributed most to the score.
- [ ] **Step 2**: Test: after 100 retrievals, bullets that were never returned have `total_strength` lower than bullets returned 10+ times (decay works as expected).
- [ ] **Step 3**: Edge case: a bullet that scores highest on the `episodic` channel but is returned when querying for a procedural task — only the `episodic_access_index` advances. This is what makes per-channel decay meaningful.

### Task 3.2: Foreground-background budget allocator

**File:** `agent/pruning/fg_bg_decomposer.py`, tests

- [ ] **Step 1**: 70/30 / 60/40 / 50/50 ratios by recency index, monotonic decrease.
- [ ] **Step 2**: Implement `allocate_fg_bg_budget(total_tokens, recency_index)`.

### Task 3.3: Distant summarizer

**File:** `agent/pruning/summarizer.py`, tests

- [ ] Implement `rule_based_summary(distant_steps)`.

### Task 3.4: Wire pruner into orchestrator

- [ ] Pass `pruned_context = pruner.prune(state.history)` to every VLM call.

### Phase 3 Acceptance

- [ ] ≥70% reduction on 15-step histories
- [ ] Orchestrator uses pruner automatically

---

# Phase 4 — Environment-Aware Multi-Model Routing (Week 4)

**Goal:** Mechanism 3 — three-tier routing with confidence escalation. In `local` mode all tiers use Qwen; in `production` mode all tiers use Gemini 3.1 variants.

### Task 4.1: VLMClient abstract base

**File:** `agent/routing/models/base.py`, tests

- [ ] Abstract `predict_action(task, dom, pruned_context) -> (Action, confidence, cost_usd)`, abstract `name`, `cost_per_million_input_tokens`, `cost_per_million_output_tokens`.

### Task 4.2: Qwen local client

**File:** `agent/routing/models/qwen_local.py`, tests

- [ ] **Step 1**: Implement `QwenLocalClient(server_url, mode)` with three modes — `simple` (short prompt, used by Tier 1), `general` (history + DOM, used by Tier 2), `full_context` (all DOM elements + pruned history, used by Tier 3). All three call `http://localhost:8001/completion`. Cost constants: `0.0` (local is free).
- [ ] **Step 2**: Mocked test with `respx` or `httpx.MockTransport` covering JSON parsing and confidence extraction from logprobs. Live `@pytest.mark.local` test hits `/health`.

### Task 4.3: Gemini cloud client

**File:** `agent/routing/models/gemini_cloud.py`, tests

- [ ] **Step 1**: Implement `GeminiCloudClient(model_id, api_key)` using `google-genai`:

```python
"""Gemini 3.1 client for production tier."""
import json
import os
from google import genai
from google.genai import types
from agent.harness.state import Action, ActionType
from agent.browser.dom_extractor import DOMState
from agent.pruning.context_window import PrunedContext, RecencyPruner
from agent.routing.models.base import VLMClient


SYSTEM_PROMPT = """You are a computer-use agent. Given a task and the current web page, predict the next action.
Respond ONLY with JSON:
{"type": "click|fill|navigate|select|scroll|finish", "target": "CSS selector or URL",
 "value": "optional", "reasoning": "brief why"}
"""

# Approximate pricing for Gemini 3.1 tiers — update when final pricing is published
PRICING = {
    "gemini-3.1-flash-lite": (0.075, 0.30),
    "gemini-3.1-flash": (0.15, 0.60),
    "gemini-3.1-pro": (1.25, 5.00),
}


class GeminiCloudClient(VLMClient):
    def __init__(self, model_id: str, api_key: str | None = None):
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Production tier requires it. No fallback."
            )
        if model_id not in PRICING:
            raise RuntimeError(f"Unknown Gemini model id: {model_id}. Update PRICING.")
        self._model_id = model_id
        self._client = genai.Client(api_key = key)
        self._in_cost, self._out_cost = PRICING[model_id]

    @property
    def name(self) -> str:
        return self._model_id

    @property
    def cost_per_million_input_tokens(self) -> float:
        return self._in_cost

    @property
    def cost_per_million_output_tokens(self) -> float:
        return self._out_cost

    async def predict_action(self, task, dom: DOMState, pruned_context: PrunedContext):
        pruner = RecencyPruner()
        context = pruner.format_for_prompt(pruned_context)
        prompt = (
            f"Task: {task}\n\nCurrent page:\n{dom.markdown}\n\n"
            f"{context}\n\nNext action (JSON only):"
        )
        response = await self._client.aio.models.generate_content(
            model = self._model_id,
            contents = prompt,
            config = types.GenerateContentConfig(
                system_instruction = SYSTEM_PROMPT,
                temperature = 0.2,
                max_output_tokens = 300,
                response_mime_type = "application/json",
            ),
        )
        parsed = json.loads(response.text.strip())
        action = Action(
            type = ActionType(parsed["type"]),
            target = parsed["target"],
            value = parsed.get("value"),
            reasoning = parsed.get("reasoning", ""),
            model_used = self.name,
        )
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count
        output_tokens = usage.candidates_token_count
        cost = (
            input_tokens / 1_000_000 * self._in_cost
            + output_tokens / 1_000_000 * self._out_cost
        )
        confidence = 0.9  # Gemini does not expose token-level logprobs by default
        action.confidence = confidence
        return action, confidence, cost
```

- [ ] **Step 2**: Mocked test verifying JSON parsing, cost calculation, and that missing `GEMINI_API_KEY` raises `RuntimeError`. Live `@pytest.mark.production` test hits the real API.

### Task 4.4: Difficulty classifier

**File:** `agent/routing/difficulty_classifier.py`, tests

- [ ] Implement heuristic `classify_difficulty(task, dom, has_memory) -> Difficulty` (EASY / MEDIUM / HARD). High-risk task keywords always return HARD; complex pages (>50 elements) always return HARD; memory-enhanced downgrades one tier.

### Task 4.5: Confidence probe

**File:** `agent/routing/confidence_probe.py`, tests

- [ ] `confidence_from_logprobs(logprobs)` using mean-logprob → exp.

### Task 4.6: Adaptive router

**File:** `agent/routing/router.py`, tests

- [ ] Implement `AdaptiveRouter(tier1, tier2, tier3)` with `THRESHOLDS = {1: 0.75, 2: 0.65, 3: 0.50}`, `route_and_predict(task, dom, pruned_context, memory_enhanced)`, `RoutingDecision` dataclass.

### Task 4.7: Client factory (env-aware)

**File:** `agent/routing/factory.py`, tests

This is the key environment switch.

- [ ] **Step 1**: Write test:

```python
import os
import pytest
from unittest.mock import patch
from agent.routing.factory import build_router


def test_factory_local_mode_uses_qwen(monkeypatch):
    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("QWEN_SERVER_URL", "http://localhost:8001")
    router = build_router()
    assert "qwen" in router.tier1.name.lower()
    assert "qwen" in router.tier3.name.lower()


def test_factory_production_mode_uses_gemini(monkeypatch):
    monkeypatch.setenv("CUTIEE_ENV", "production")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL_TIER1", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GEMINI_MODEL_TIER2", "gemini-3.1-flash")
    monkeypatch.setenv("GEMINI_MODEL_TIER3", "gemini-3.1-pro")
    with patch("agent.routing.models.gemini_cloud.genai.Client"):
        router = build_router()
    assert "gemini" in router.tier1.name.lower()
    assert router.tier3.name == "gemini-3.1-pro"


def test_factory_errors_on_unset_env(monkeypatch):
    monkeypatch.delenv("CUTIEE_ENV", raising = False)
    with pytest.raises(RuntimeError, match = "CUTIEE_ENV"):
        build_router()
```

- [ ] **Step 2**: Implement factory:

```python
"""Build an AdaptiveRouter based on CUTIEE_ENV. No cross-environment fallback."""
import os
from agent.routing.router import AdaptiveRouter
from agent.routing.models.qwen_local import QwenLocalClient
from agent.routing.models.gemini_cloud import GeminiCloudClient


def build_router() -> AdaptiveRouter:
    env = os.environ.get("CUTIEE_ENV")
    if env == "local":
        server_url = os.environ.get("QWEN_SERVER_URL")
        if not server_url:
            raise RuntimeError("QWEN_SERVER_URL required in local mode")
        return AdaptiveRouter(
            tier1 = QwenLocalClient(server_url = server_url, mode = "simple"),
            tier2 = QwenLocalClient(server_url = server_url, mode = "general"),
            tier3 = QwenLocalClient(server_url = server_url, mode = "full_context"),
        )
    if env == "production":
        return AdaptiveRouter(
            tier1 = GeminiCloudClient(model_id = os.environ["GEMINI_MODEL_TIER1"]),
            tier2 = GeminiCloudClient(model_id = os.environ["GEMINI_MODEL_TIER2"]),
            tier3 = GeminiCloudClient(model_id = os.environ["GEMINI_MODEL_TIER3"]),
        )
    raise RuntimeError(
        f"CUTIEE_ENV must be 'local' or 'production', got {env!r}. No fallback."
    )
```

### Task 4.8: Wire router into orchestrator

- [ ] Orchestrator accepts `router: AdaptiveRouter | None`. When set, replace the single-client path with `router.route_and_predict(...)`. Persist `decision.tier` to `Step.tier`.

### Phase 4 Acceptance

- [ ] Factory builds the correct router per `CUTIEE_ENV`
- [ ] Missing or invalid `CUTIEE_ENV` raises
- [ ] Qwen client (mocked + live-local) works
- [ ] Gemini client (mocked + live-production) works
- [ ] Router escalates on low confidence
- [ ] High-risk tasks go to Tier 3

---

# Phase 5 — Django UI, Auth, JSON API, Data Visualization (End of Week 4)

**Goal:** Full user-facing application matching the miramemoria visual language. Satisfies INFO490 Part 2.

### Task 5.1: Accounts — Google OAuth primary, email/password secondary

**Files:**
- `apps/accounts/views.py`, `urls.py`, `templates/accounts/*`
- root `cutiee_site/urls.py` includes `path("auth/", include("allauth.urls"))`

Google OAuth via `django-allauth` is the primary auth flow. Email/password is supported as a secondary option for users who do not want to use Google.

- [ ] **Step 1**: Template `accounts/login.html` extends `base.html` and renders a prominent "Sign in with Google" button using the miramemoria `.btn-gradient` utility:

```html
{% extends "base.html" %}
{% load socialaccount %}
{% block content %}
<div class="page-container page-container--tight">
  <div class="glass-surface rounded-[16px] p-8 max-w-md mx-auto mt-16">
    <h1 class="font-manrope font-extrabold text-[28px] text-mm-text mb-2">Sign in to CUTIEE</h1>
    <p class="font-inter text-mm-muted text-sm mb-6">
      Delegate repetitive web tasks to an agent that learns from your workflows.
    </p>

    {% get_providers as socialaccount_providers %}
    <a href="{% provider_login_url 'google' process='login' %}" class="btn-gradient flex items-center justify-center gap-3 w-full py-3 px-4 font-semibold text-white">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M21.35 11.1H12v2.96h5.35c-.23 1.54-1.76 4.5-5.35 4.5-3.22 0-5.85-2.67-5.85-5.96s2.63-5.96 5.85-5.96c1.84 0 3.07.78 3.77 1.46l2.57-2.48C16.76 4.1 14.57 3 12 3 7.03 3 3 7.03 3 12s4.03 9 9 9c5.19 0 8.64-3.65 8.64-8.79 0-.59-.06-1.04-.14-1.41z"/>
      </svg>
      Sign in with Google
    </a>

    <div class="flex items-center gap-3 my-6">
      <div class="flex-1 h-px bg-mm-border"></div>
      <span class="text-xs uppercase text-mm-muted tracking-wider">Or</span>
      <div class="flex-1 h-px bg-mm-border"></div>
    </div>

    <form method="post" action="{% url 'account_login' %}">
      {% csrf_token %}
      {{ form.as_p }}
      <button type="submit" class="btn-secondary w-full py-2">Sign in with email</button>
    </form>
    <p class="text-sm text-mm-muted mt-4 text-center">
      New here? <a href="{% url 'account_signup' %}" class="text-mm-primary">Create an account</a>
    </p>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2**: Test the Google-login redirect path:

```python
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_google_login_url_present_on_login_page(client):
    resp = client.get(reverse("account_login"))
    assert resp.status_code == 200
    assert b"Sign in with Google" in resp.content
    assert b"/auth/google/login/" in resp.content


@pytest.mark.django_db
def test_logout_redirects_to_login(client, cutiee_user):
    # `cutiee_user` is a pytest fixture in tests/conftest.py that creates a
    # :User node via apps.accounts.neo4j_auth_backend and returns a proxy
    # object with a .pk attribute so Django's force_login still works.
    user = cutiee_user(username = "alice", password = "testpass")
    client.force_login(user)
    resp = client.post(reverse("account_logout"))
    assert resp.status_code in (302, 200)
```

- [ ] **Step 3**: Configure allauth settings (already added in Phase 0 Task 0.3 Step 2).

- [ ] **Step 4**: Templates `account_signup.html`, `account_logout.html` — use allauth's templates as a starting point; override only the body to match miramemoria's glass-surface styling.

- [ ] **Step 5**: For development, a Google Cloud Console project is required. Document in README: create OAuth 2.0 Client ID, add `http://localhost:8000/auth/google/login/callback/` as an authorized redirect URI, add the client id + secret to `.env`.

### Task 5.2: Tasks views + service layer + JSON API

**Files:** `apps/tasks/{views.py,urls.py,forms.py,services.py,api.py,templates/tasks/*}`

- [ ] **Step 1**: Write `apps/tasks/forms.py` with a `ModelForm` for `Task`.
- [ ] **Step 2**: Write `apps/tasks/services.py` — the Django-to-agent bridge. It calls `build_router()` (env-aware), instantiates `ProceduralMemory(user_id)`, `SemanticMemory(user_id)`, `RecencyPruner()`, creates an `Orchestrator`, runs the task, persists `Execution` and `Step` rows.
- [ ] **Step 3**: Views: `TaskListView(LoginRequiredMixin, ListView)`, `TaskDetailView(LoginRequiredMixin, DetailView)`, `create_task` FBV.
- [ ] **Step 4**: API endpoints in `apps/tasks/api.py`:
  - `POST /tasks/<pk>/run/` — triggers `run_task_for_user`
  - `GET /tasks/api/<pk>/status/` — polling endpoint for HTMX
  - `GET /tasks/api/cost-summary/` — totals for dashboard
  - `GET /tasks/api/cost-timeseries/` — daily totals for charts
- [ ] **Step 5**: Templates `list.html`, `detail.html`, `create.html`, `dashboard.html` — all use glass-morphism cards, `#6C86C0` accent, Inter + Manrope fonts. Dashboard embeds three Chart.js charts: daily cost, tier distribution, replay-vs-VLM.

### Task 5.3: Memory dashboard

**Files:** `apps/memory_app/{views.py,urls.py,templates/memory_app/*}`

- [ ] List view with user's templates (success count, domain, token size, last used). Detail view shows parameterized steps and a "mark stale" action. Export endpoint `/memory/templates/export/` returning JSON (satisfies Part 2 export requirement).

### Task 5.4: Audit log view

**Files:** `apps/audit/{views.py,urls.py,templates/audit/list.html}`

- [ ] Paginated list scoped to `request.user`. Columns: timestamp, task, step, model, tier, cost, risk, approval status.

### Task 5.5: Safety layer

**Files:** `agent/safety/{risk_classifier.py,approval_gate.py,audit.py}`, tests

- [ ] `classify_risk(action, task) -> RiskLevel`, `require_approval(message, callback)`, `AuditLog` backed by the Django `AuditEntry` model.

### Task 5.6: Data visualization

- [ ] Confirm Chart.js renders the three charts, wired to `/tasks/api/cost-timeseries/` and `/tasks/api/cost-summary/`. Add a "Dashboard" nav entry.

### Task 5.7: Marketing landing page at `/`

**Goal:** A polished, unauthenticated landing page modeled on `/Users/edwardhu/Desktop/INFO490/miramemoria/app/memoria/templates/memoria/landing.html`. It is the first thing graders and new users see.

**Files:**
- Create: `apps/landing/__init__.py`, `apps.py`, `views.py`, `urls.py`
- Create: `apps/landing/templates/landing/landing.html` (single-file template, does NOT extend `base.html`)
- Create: `apps/landing/static/landing/landing.css` (optional scoped extras)
- Modify: `cutiee_site/urls.py` — root `""` routes to `landing.views.index`
- Modify: `apps/tasks/views.py` — `TaskListView` is the post-login home at `/tasks/`

**Behavior:** `GET /` renders `landing.html` for anonymous users; authenticated users redirect to `/tasks/`.

- [ ] **Step 1**: Create the `apps.landing` Django app and register in `INSTALLED_APPS`.

- [ ] **Step 2**: Write `apps/landing/views.py`:

```python
from django.shortcuts import redirect, render


def index(request):
    if request.user.is_authenticated:
        return redirect("tasks:list")
    return render(request, "landing/landing.html")
```

Wire `apps/landing/urls.py`:

```python
from django.urls import path
from . import views

app_name = "landing"
urlpatterns = [path("", views.index, name = "index")]
```

Register in `cutiee_site/urls.py`:

```python
path("", include("apps.landing.urls")),
```

- [ ] **Step 3**: Write `apps/landing/templates/landing/landing.html` mirroring miramemoria's `landing.html`:

  1. **Sticky glass header**: CUTIEE logo as gradient text (`bg-clip-text text-transparent` from `from-mm-primary` to `to-mm-primary-end`), "Sign in with Google" CTA on the right (`cta-gradient` linking to `{% url 'google_login' %}`).
  2. **Hero** (`pt-20`): pulsing-dot pill badge "Computer use agent · live demo on Render", H1 with gradient first line "Your computer use agent," + regular second line "at $0 per recurring task.", Inter muted subtitle "CUTIEE replays learned workflows, prunes stale context, and routes each action to the cheapest viable model — so your agent gets smarter and cheaper over time.", two-button CTA stack (primary "Sign in with Google" → `/auth/google/login/`, ghost "See how it works" smooth-scrolls to feature grid).
  3. **Feature grid** — 4 `.feature-card` glass surfaces, each with a gradient-filled icon:
     - Procedural Memory Replay — zero-cost recurring tasks
     - Temporal Recency Pruning — 70%+ token savings on long workflows
     - Self-Evolving Templates — templates patch themselves when UIs change
     - Multi-Model Routing — every action to the cheapest viable tier
  4. **Cost comparison strip**: bold row "Gemini-only baseline: ~$0.30/task · CUTIEE hybrid: ~$0.004/task · 98.7% reduction" with an optional Chart.js sparkline.
  5. **Affiliations section**: floating Illinois + Illinois TEC institution cards using the exact `.institution-logo-card` keyframes (`@keyframes float`) copied from miramemoria.
  6. **Footer**: small row with links to `/about`, `/privacy`, `/help` and a `© 2026 CUTIEE` line.

  Inline CSS block mirrors miramemoria verbatim: `.landing-bg` radial gradients, `.cta-gradient`, `.cta-ghost`, `.feature-card`, `.institution-logo-card`, `@media (max-width: 640px)` mobile stack. Preconnect + load Inter and Manrope via Google Fonts. Tailwind via CDN (`<script src="https://cdn.tailwindcss.com"></script>`) with inline config adding `mm-primary: #6C86C0`, `mm-muted: #64748b`, etc.

- [ ] **Step 4**: Copy institution logo assets so the floating cards render:

```bash
mkdir -p static/images
cp /Users/edwardhu/Desktop/INFO490/miramemoria/static/images/illinois-logo.png static/images/ 2>/dev/null || true
cp /Users/edwardhu/Desktop/INFO490/miramemoria/static/images/illinois-tec-logo.png static/images/ 2>/dev/null || true
```

- [ ] **Step 5**: Tests in `tests/apps/landing/test_views.py`:

```python
import pytest
from django.urls import reverse


def test_landing_renders_for_anonymous(client):
    resp = client.get(reverse("landing:index"))
    assert resp.status_code == 200
    assert b"CUTIEE" in resp.content
    assert b"Sign in with Google" in resp.content


@pytest.mark.django_db
def test_authenticated_user_redirects_to_tasks(client, cutiee_user):
    user = cutiee_user(username = "alice", password = "testpass")
    client.force_login(user)
    resp = client.get(reverse("landing:index"))
    assert resp.status_code == 302
    assert resp.url.startswith("/tasks/")
```

- [ ] **Step 6**: Manual smoke: visit `http://localhost:8000/`, confirm hero, feature cards, CTA buttons, institution logos animate. Resize to <640px and verify the hero CTA stack collapses.

**Accept** when: anonymous users see the landing; authenticated users redirect to `/tasks/`; visual parity with miramemoria is obvious (same fonts, colors, glass surfaces, gradient text, floating logos).

### Phase 5 Acceptance

- [ ] Users sign up, log in, submit a task, see execution progress (HTMX-polled), browse memory, view audit, see cost dashboard
- [ ] Visual design matches miramemoria (colors, fonts, glass-morphism)
- [ ] `uv run python manage.py check --deploy` clean
- [ ] `uv run pytest tests/apps/` green

---

# Phase 6 — Demos: Flask CI-safe + Real-World Showcase (Final Week)

**Goal:** Two demo tiers. Flask sites prove correctness cheaply in CI. Real productivity tools (Google Sheets, Google Slides) prove product value for the Technical Report recordings.

### Task 6.1: Flask demo sites

**Files:**
- `demo_sites/spreadsheet_site/app.py` (port 5001) — 10×5 grid, edit cells, sort, sum
- `demo_sites/slides_site/app.py` (port 5002) — 3 initial slides, add/edit/reorder
- `demo_sites/form_site/app.py` (port 5003) — 4-step wizard
- `scripts/start_demo_sites.py`

### Task 6.2: Flask-site integration tests (CI-safe)

**Files:**
- `tests/integration/test_scenario_1_replay.py` — on spreadsheet site
- `tests/integration/test_scenario_2_pruning.py` — 20-step spreadsheet navigation
- `tests/integration/test_scenario_3_routing.py` — 10-task batch across sites
- `tests/integration/test_scenario_4_self_healing.py` — mutate selector between runs
- `tests/integration/test_scenario_5_safety_gate.py` — approval flow on form submit

All use mocked VLM clients. Mark `@pytest.mark.integration` and `@pytest.mark.slow`.

### Task 6.3: Real-world showcase demos

**Files:** `tests/integration/showcase/test_{sheets_sort,sheets_formula,slides_add_slide,slides_reorder}.py`

- [ ] `conftest.py` loads Playwright `storage_state.json` (tester captures this once via `playwright codegen`). Skip if absent.
- [ ] Each test navigates to a test Google Sheet / Slides document and drives the agent. Mark `@pytest.mark.showcase` — not run in CI.

### Task 6.4: Django E2E test

- [ ] `pytest-django` client POSTs `/tasks/create/`, polls `task_status`, asserts JSON.

### Phase 6 Acceptance

- [ ] All 5 Flask scenarios pass with mock VLM
- [ ] At least 4 of 4 showcase demos pass manually
- [ ] Django E2E test passes
- [ ] Screen captures saved to `docs/evaluation/demo_recordings/`

---

# Phase 7 — Evaluation, Cost Analysis, INFO490 Deliverables

### Task 7.1: Test cases (Part 4.1)

**File:** `docs/evaluation/test_cases.md`

Document 5+ cases, each with Input · Expected Behavior · Actual Output · Quality · Latency · Tier Distribution · Cost.

Candidates:
  1. Google Sheets: sort rows by column B (novel)
  2. Google Sheets: sort rows by column B (replay)
  3. Google Sheets: add `=SUM(A1:A10)` in A11
  4. Google Slides: add new slide with title "Q2 Revenue" after slide 2
  5. Google Slides: move slide 3 to first position
  6. Flask form wizard: 4-step submission (long-horizon, pruning-heavy)
  7. Optional: archive Gmail emails from a sender (safety gate)

### Task 7.2: Failure analysis (Part 4.2)

**File:** `docs/evaluation/failure_analysis.md`

Document 2+ real failures:
  1. Google Sheets toolbar moved between runs — template self-healed, measure cost delta
  2. Qwen low-confidence on slide reorder — escalated to Tier 3, document reasoning
  3. Google session expired mid-task — production concern, discuss in Part 4.5

### Task 7.3: Improvement case (Part 4.3)

**File:** `docs/evaluation/improvement.md`

Candidates:
  - Lowered Tier-1 threshold 0.85 → 0.75 for Qwen (before/after replay hit rate)
  - Added FG/BG budget allocation (token reduction delta on 30-step task)
  - Template parameterization of spreadsheet ranges (`$RANGE{A1:B10}`)

### Task 7.4: Cost comparison (Part 4.4)

**Files:** `scripts/benchmark_costs.py`, `docs/evaluation/cost_comparison.md`

Benchmark script:
```python
"""Compare CUTIEE (both envs) against naive API-only baselines."""
# 1. Local env (CUTIEE_ENV=local): all tiers Qwen, effectively $0 per task
# 2. Production env (CUTIEE_ENV=production): tiered Gemini, cost per task
# 3. API-only baseline: every action calls gemini-3.1-pro directly (strawman)
# Report per-task and aggregate costs, plus replay hit rate and average
# latency. Output markdown table to docs/evaluation/cost_comparison.md.
```

Cost comparison doc covers:
  - Compute usage: Qwen Q4_K_M ~2GB RAM, CPU, ~1-3s per call; Gemini 3.1 Flash ~500ms network latency
  - API cost: use real Gemini 3.1 Flash pricing at benchmark time
  - When CUTIEE is cheaper: recurring tasks (100% savings via replay), long tasks (pruning), routing avoids pro-tier for simple actions
  - When CUTIEE is more expensive: 100%-novel workloads pay the local-compute overhead without replay savings
  - Render hosting cost estimate: $7/mo starter dyno; scale to $25/mo standard for production workload

### Task 7.5: Production readiness (Part 4.5)

**File:** `docs/evaluation/production_readiness.md`

Cover:
  - **Scaling**: Gunicorn + multiple Playwright workers; 10K users/day ≈ 7 concurrent at peak (1-min task). Horizontal scaling via Celery queue.
  - **Rate limiting**: `django-ratelimit` per-IP + per-user daily quota (e.g., 50 tasks/day).
  - **Privacy**: credentials in `SemanticFact(is_credential=True)` — prod should swap to OS keychain / HashiCorp Vault. User-scoped audit log. Task descriptions may contain PII — add retention toggle.
  - **Monitoring**: structlog + Sentry + Prometheus (tier call counts, cost, template hit rate, replay success rate). Render has built-in log streaming.
  - **Render-specific**: `render.yaml` committed; `PORT` env bound to Gunicorn; Whitenoise for static files.

### Task 7.6: Technical Report

**File:** `docs/technical_report.md` (4-6 pages)

Sections:
  1. Product Overview
  2. Django System Architecture — diagram of apps, models, views, JSON API, auth flow
  3. AI Integration — three mechanisms, environment-aware stack (Qwen vs Gemini 3.1), flow diagram. Answer: "What would an API-only (Gemini-only-always) version look like? Why did we not choose that?" Reference the cost-delta and control-over-routing advantages.
  4. Evaluation & Failure Analysis
  5. Cost & Production Readiness

Export: `pandoc docs/technical_report.md -o docs/technical_report.pdf`.

### Task 7.7: Final README.md

- Setup for both envs (local + production)
- Dependencies (Python 3.11+, `llama.cpp` binary on PATH for local, Gemini API key for production)
- Running the app
- Access points to the AI feature
- Deploy-to-Render instructions referencing `render.yaml`

### Task 7.8: README_AI.md

- AI workflow: task input → orchestrator → memory check → pruned context → tiered routing (env-aware) → browser execution → template storage / self-healing → result
- Model selection: Qwen3.5 0.8B (local), Gemini 3.1 (production: flash-lite, flash, pro per tier)
- Design decisions: why the environment split, why N=3, why 0.85, why self-evolving templates, why no silent fallbacks

### Phase 7 Acceptance

- [ ] All `docs/evaluation/*.md` exist and complete
- [ ] `docs/technical_report.pdf` rendered, 4-6 pages
- [ ] Both README files polished
- [ ] `scripts/benchmark_costs.py` runs in both envs and emits report
- [ ] `uv run pytest -m "not local and not production and not showcase"` passes
- [ ] `uv run python manage.py check --deploy` clean
- [ ] Repository pushed to `https://github.com/Edward-H26/CUTIEE.git`
- [ ] Render deployment live at `cutiee.onrender.com` (optional but highly recommended)

### Phase 7 Final Checkpoint

Full suite:

```bash
uv run pytest -v -m "not local and not production and not showcase"
uv run mypy agent/ apps/
uv run ruff check agent/ apps/ tests/
python scripts/benchmark_costs.py
```

Summarize: total tests, coverage per layer, cost benchmark result across both environments.

---

# Critical Files Reference

| File | Phase | Purpose |
|------|-------|---------|
| `docs/part1_product_refinement.md` | 0 | Assignment Part 1 |
| `pyproject.toml`, `.env`, `.env.example` | 0 | Dependencies + config |
| `render.yaml` | 0 | Render deployment |
| `CLAUDE.md` | 0 | Project briefing |
| `cutiee_site/settings.py` | 0 | Django settings + `CUTIEE_ENV` check |
| `templates/base.html`, `static/css/*` | 0 | Miramemoria design inheritance |
| `docker-compose.yml` | 0 | Local Neo4j 5 container |
| `agent/persistence/neo4j_client.py` | 0 | Driver + `_run_query` / `_run_single` (from miramemoria) |
| `agent/persistence/bootstrap.py` | 0 | Idempotent Cypher constraints + indexes |
| `apps/accounts/neo4j_auth_backend.py` | 0 | Django auth backend over Neo4j (from miramemoria) |
| `cutiee_site/neo4j_session_backend.py` | 0 | Django session engine over Neo4j (from miramemoria) |
| `agent/harness/state.py` | 1 | In-memory dataclasses |
| `agent/browser/controller.py` | 1 | Playwright lifecycle |
| `agent/browser/dom_extractor.py` | 1 | Compact DOM |
| `apps/{tasks,memory_app,audit}/repo.py` | 1 | Cypher-backed repositories (no Django ORM) |
| `apps/memory_app/bullet.py` | 1 | `Bullet` / `DeltaUpdate` dataclasses (from LongTermMemoryBasedSelfEvolvingAlgorithm) |
| `agent/harness/orchestrator.py` | 1, 2, 3, 4 | Agent loop (evolves each phase) |
| `agent/memory/ace_memory.py` | 2 | Three-strength bullet retrieval, apply_delta, refine |
| `agent/memory/decay.py` | 2 | Per-channel exponential decay (semantic 0.01, episodic 0.05, procedural 0.002) |
| `agent/memory/reflector.py`, `quality_gate.py`, `curator.py`, `pipeline.py` | 2 | Reflect → Gate → Curate → Apply loop |
| `agent/memory/replay.py` | 2 | Procedural-bullet replay with self-healing DeltaUpdate |
| `agent/pruning/context_window.py` | 3 | N=3 sliding window + ACE access-clock advancement |
| `agent/routing/router.py` | 4 | Tier selection + escalation |
| `agent/routing/factory.py` | 4 | Env-aware client assembly |
| `agent/routing/models/qwen_local.py` | 4 | Qwen3.5 0.8B (local) |
| `agent/routing/models/gemini_cloud.py` | 4 | Gemini 3.1 variants (production) |
| `apps/tasks/views.py`, `api.py`, `services.py` | 5 | Django bridge to agent |
| `demo_sites/*/app.py` | 6 | Flask test targets |
| `scripts/benchmark_costs.py` | 7 | Cost benchmark |
| `docs/technical_report.md` | 7 | 4-6 page report |
| `docs/evaluation/*.md` | 7 | Part 4 deliverables |
| `README.md`, `README_AI.md` | 7 | Required deliverables |

---

# Stop Points Summary

1. **After Phase 0** — Rename, git init, scaffold, Part 1 doc. User commits + pushes.
2. **After Phase 1** — Mandatory stop per user request. Show test output.
3. **After Phase 2** — Memory replay + self-evolving templates green.
4. **After Phase 3** — ≥70% token reduction target met.
5. **After Phase 4** — Env-aware routing green in both local and production modes.
6. **After Phase 5** — Django UI complete (auth, dashboard, API, visualization) with miramemoria look.
7. **After Phase 6** — Five Flask scenarios + showcase demos recorded.
8. **After Phase 7** — Report + READMEs + Render deploy ready for INFO490 submission.
9. **After Phase 8 (ULTRAREVIEW)** — Functional test matrix green across all nine review cells, Neo4j constraints verified in both environments, self-evolving loop observed across at least three task reruns.

---

# Verification (End-to-End)

```bash
# Unit + Django (no model or API deps)
uv run pytest -m "not local and not production and not showcase" -v

# Local stack (requires llama-server)
CUTIEE_ENV=local uv run pytest -m local -v

# Production stack (requires GEMINI_API_KEY)
CUTIEE_ENV=production uv run pytest -m production -v

# Integration (Flask sites)
uv run python scripts/start_demo_sites.py &
uv run pytest -m integration -v

# Django deployment check
uv run python manage.py check --deploy

# Manual UX pass
uv run python manage.py runserver &
open http://localhost:8000/accounts/login/
# Submit "Sort rows by column B" on demo spreadsheet site → observe first run (full pipeline)
# Submit same task → observe replay (zero cost)

# Cost benchmark
CUTIEE_ENV=local python scripts/benchmark_costs.py
CUTIEE_ENV=production python scripts/benchmark_costs.py

# Type + lint
uv run mypy agent/ apps/
uv run ruff check agent/ apps/ tests/
```

Expected:
- All non-env-specific tests green
- Local env tests green with llama-server running
- Production env tests green with Gemini key set
- Integration tests pass against Flask sites
- Django deployment check clean, mypy clean, ruff clean
- Benchmark: local env ≈ $0 per task, production env shows tiered Gemini cost with replay savings
- Django UI responsive in miramemoria visual language (task submit → HTMX live progress → Chart.js dashboard updates)

---

# Phase 8 — ULTRAREVIEW: End-to-End Functional Review Matrix

**Goal:** After Phase 7 is complete, exercise every user-visible flow and every subsystem boundary once, with the system in its real runtime configuration (Neo4j up, Qwen up, Playwright installed). The purpose is to catch regressions that unit tests miss and to produce the evidence artifacts referenced in `docs/technical_report.md` (screen recordings, Cypher query counts, cost ledgers).

The review runs in both environments back-to-back. A cell is "green" only when both columns pass.

### Review Matrix

| # | Cell | Verification command / action | Evidence artifact | Acceptance |
|---|------|------------------------------|-------------------|------------|
| 1 | **Neo4j reachability** | `cypher-shell -a "$NEO4J_BOLT_URL" -u "$NEO4J_USERNAME" -p "$NEO4J_PASSWORD" "SHOW CONSTRAINTS"` | constraint list screenshot | 9 constraints listed (user_id, user_email, session_key, task_id, execution_id, step_id, template_id, fact_id, audit_id) |
| 2 | **Neo4j bootstrap idempotence** | Run `uv run python -m agent.persistence.bootstrap` three times in a row | stdout | Each run succeeds without raising; no duplicate-constraint errors |
| 3 | **Auth backend (Neo4j)** | Sign up with email `review@cutiee.dev` via `/accounts/signup/`, then `MATCH (u:User {email: "review@cutiee.dev"}) RETURN u` | Cypher output | Exactly one `:User` node returned; `password_hash` is a bcrypt-style prefix, never plaintext |
| 4 | **Session backend (Neo4j)** | Log in, then `MATCH (s:Session) RETURN s.session_key, s.expire LIMIT 5` | Cypher output | At least one session row; `expire` is 14 days from now (±1 min) |
| 5 | **Landing page** | Open `http://localhost:8000/` as anonymous user (Chrome) | screenshot | Hero, feature grid, affiliations render; "Sign in with Google" CTA present; page weight < 500 KB |
| 6 | **Google OAuth flow** | Click "Sign in with Google" → complete OAuth → land on `/tasks/` | screenshot + audit row | Authenticated user visible on `/tasks/`; one `:AuditEntry {action: "oauth_login"}` created |
| 7 | **Task create (local, Qwen)** | Submit "Sort rows by column B" on the Flask spreadsheet site at `http://localhost:5001` | screen recording | Orchestrator emits ≥ 3 steps; first run spends > 0 VLM calls on tier 1 Qwen; all tests verify URL |
| 8 | **Procedural replay** | Submit the same task a second time (same user) | Chart.js dashboard + `total_cost_usd` on the execution detail page | Second run reports `replay_used = true`, `total_cost_usd == 0`, ≥ 1 procedural bullet retrieved |
| 9 | **Self-evolving DeltaUpdate** | Between runs 2 and 3, rename a button on the Flask site from `#submit` to `#submit-btn` | Neo4j `(:MemoryBullet)` diff + execution row | Run 3 triggers `recovery_callback`; a `DeltaUpdate` applies with one `update_bullets` entry (`harmful += 1`, `procedural_strength -= 10`) and one `new_bullets` replacement; run 4 replays cleanly |
| 10 | **Temporal pruning** | Submit the Flask form-wizard task (`http://localhost:5003`) which generates a 20-step history | Trace length comparison | Pruned context token count ≤ 30% of the raw trace length |
| 11 | **Access-clock decay** | Retrieve a bullet 10 times with `memory_type="episodic"`; then retrieve unrelated bullets 200 times | Cypher: `MATCH (b:MemoryBullet {id: $id}) RETURN b.episodic_strength` | Bullet's `episodic_strength` drops ≥ 50% over the 200-tick window (EPISODIC_DECAY_RATE = 0.05 validated) |
| 12 | **Quality gate rejection** | Feed the reflector a trace where `output_valid = 0` | `docs/evaluation/gate_diagnostics.json` | Gate rejects with `gate_score < 0.60`; no `DeltaUpdate` applied; diagnostics file written |
| 13 | **Multi-tier routing (local)** | Submit a simple task (tier 1) and a complex task (tier 3) | `Step.tier` column | Simple task resolves at tier 1; complex task escalates to tier 3 with a low-confidence reason recorded |
| 14 | **Multi-tier routing (production)** | Same as #13 with `CUTIEE_ENV=production` | Cost ledger in `/audit/` | tier 1 calls use `gemini-3.1-flash-lite`, tier 3 uses `gemini-3.1-pro`, cost per tier visible |
| 15 | **Safety gate** | Submit "Delete my account" on a mock site whose submit button matches a high-risk tag | UI screenshot | Modal approval dialog appears; rejecting it aborts the execution and writes `AuditEntry {approval_status: "rejected"}` |
| 16 | **Credential safety** | Store a credential bullet (`tags=["credential:example.com"]`), then call `ACEMemory.as_prompt_block(retrieved)` with a matching query | prompt string | Credential content is absent from the prompt block even though the bullet matched the query |
| 17 | **Chart.js dashboard** | Load `/tasks/dashboard/` after ≥ 5 task runs | screenshot | Three charts render (daily cost, tier distribution, replay-vs-VLM); last 7 days of data |
| 18 | **JSON API** | `curl -b cookies.txt http://localhost:8000/tasks/api/cost-summary/` | JSON | Valid JSON with `daily_cost`, `tier_distribution`, `replay_ratio` keys |
| 19 | **Memory export** | Hit `/memory/templates/export/` as authenticated user | downloaded JSON | JSON includes every procedural bullet scoped to the user, no bullets from other users |
| 20 | **`manage.py check --deploy`** | `DEBUG=False uv run python manage.py check --deploy` | stdout | Zero warnings |
| 21 | **Playwright install check** | `uv run playwright --version && uv run python -c "from playwright.async_api import async_playwright; print('ok')"` | stdout | Both print cleanly |
| 22 | **Render deployment** | Deploy to Render via dashboard; open `https://cutiee.onrender.com/` | screenshot + health check | 200 from `/`, 200 from `/api/vlm-health/` with `{status: "ready", env: "production"}` |
| 23 | **Cost benchmark cross-env** | `scripts/benchmark_costs.py` in both envs | markdown output | `docs/evaluation/cost_comparison.md` shows ≥ 95% cost reduction on replay workloads |
| 24 | **Self-evolving telemetry** | After 20 task runs, `MATCH (t:ProceduralTemplate)-[r:SUPERSEDED_BY]->(t2) RETURN count(r)` | Cypher output | At least one supersedure edge exists, proving the lineage is tracked |

### Review commands (in order)

```bash
# 0. Preconditions
[ "$CUTIEE_ENV" ] || (echo "Set CUTIEE_ENV"; exit 1)
./scripts/neo4j_up.sh                                    # cells 1, 2
uv run python -m agent.persistence.bootstrap             # cell 2

# 1. Full unit + integration suite
uv run pytest -m "not showcase" -v                       # cells 3, 4, 8, 9, 11, 12, 13, 15, 16

# 2. Local env live tests
CUTIEE_ENV=local uv run pytest -m local -v               # cell 7 (requires llama-server)

# 3. Production env live tests
CUTIEE_ENV=production uv run pytest -m production -v     # cell 14 (requires GEMINI_API_KEY)

# 4. Manual Playwright sweep
uv run python manage.py runserver &
uv run python scripts/start_demo_sites.py &
uv run pytest -m showcase -v                             # cells 7, 8, 9, 10, 17, 19

# 5. Deployment + API checks
DEBUG=False uv run python manage.py check --deploy       # cell 20
curl -sb cookies.txt http://localhost:8000/tasks/api/cost-summary/ | jq .   # cell 18

# 6. Browser walkthrough (chrome-devtools skill preferred)
node .claude/skills/chrome-devtools/scripts/navigate.js --url http://localhost:8000/
node .claude/skills/chrome-devtools/scripts/screenshot.js --url http://localhost:8000/ --output docs/evaluation/screenshots/landing.png
node .claude/skills/chrome-devtools/scripts/screenshot.js --url http://localhost:8000/tasks/dashboard/ --output docs/evaluation/screenshots/dashboard.png

# 7. Cost benchmark
CUTIEE_ENV=local uv run python scripts/benchmark_costs.py     # cell 23
CUTIEE_ENV=production uv run python scripts/benchmark_costs.py

# 8. Lineage query
cypher-shell -a "$NEO4J_BOLT_URL" -u "$NEO4J_USERNAME" -p "$NEO4J_PASSWORD" \
  "MATCH (t:ProceduralTemplate)-[r:SUPERSEDED_BY]->(t2) RETURN count(r) AS evolutions"   # cell 24
```

### Evidence bundle

All cell outputs are copied into `docs/evaluation/ultrareview/` as:

- `01_constraints.txt`, `02_bootstrap.log`, `03_auth_cypher.txt`, `04_session_cypher.txt`
- `screenshots/{landing,dashboard,approval_modal,task_detail}.png`
- `recordings/{task_create_run1.mp4,task_create_run2_replay.mp4,self_healing_run3.mp4}`
- `gate_diagnostics.json` (cell 12)
- `cost_comparison.md` (cell 23)
- `supersedure_count.txt` (cell 24)

The Technical Report links to this bundle as supporting evidence for the "self-Evolving" claim. If any cell fails, the plan stops here and the failure is fixed before the report is finalized.

### Phase 8 Acceptance

- [ ] All 24 review cells green in both environments
- [ ] Evidence bundle committed under `docs/evaluation/ultrareview/`
- [ ] Technical Report updated with at least three screenshots + one Cypher query from the bundle
- [ ] No `DETACH DELETE` ran against unintended user data during the review (cross-tenant isolation held)
- [ ] `uv run pytest -v` overall pass count matches Phase 7's baseline (no regressions introduced by the review itself)
