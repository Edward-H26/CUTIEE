# CUTIEE

**Computer Use agentIc-framework with Token-efficient harnEss Engineering**

A Django web application that wraps a computer-use agent with three
cost-reduction mechanisms (procedural memory replay, temporal recency
pruning, multi-tier model routing) and a self-evolving memory subsystem.
Recurring tasks drop to zero VLM cost; novel tasks compose tiers so the
expensive frontier model only fires for the hard 5% of decisions.

INFO490 final project (A10).

## What it does

- Submit a natural-language task (for example, "sort my Sheets by column B").
- The agent checks procedural memory first. If a learned workflow matches
  above the similarity threshold, the planner reconstructs the action
  sequence and the browser controller replays it through Playwright at
  zero inference cost.
- If no replay path exists, the orchestrator runs the observe-reason-act
  loop. The pruner trims the trajectory before each model call, the
  router picks the cheapest viable tier, and the safety gate suspends
  high-risk actions for explicit user approval.
- Every step is audited. The cost dashboard plots daily spend and tier
  distribution. The memory dashboard exposes the learned bullet store
  and the procedural templates.

## Quickstart

### Prerequisites

- Python 3.11+
- `uv` (https://docs.astral.sh/uv/) or `pip`
- Docker (for the local Neo4j container)
### Local setup

```bash
git clone https://github.com/Edward-H26/CUTIEE.git
cd CUTIEE
uv sync
uv run playwright install chromium

# Copy the env template and fill in values
cp .env.example .env
# CUTIEE_ENV=local (mock CU) or production (real Gemini),
# NEO4J_*, GOOGLE_CLIENT_ID/SECRET, GEMINI_API_KEY (production only)

# Start Neo4j (local) + Django (one shot)
./scripts/dev.sh
```

The dev script starts Neo4j in Docker and runs `manage.py runserver` on
port 8000. With `CUTIEE_ENV=local` the agent uses `MockComputerUseClient`
(scripted demo actions, no API calls). With `CUTIEE_ENV=production` and a
`GEMINI_API_KEY`, every task runs through the live Gemini Computer Use tool.

Open http://localhost:8000 . Sign in with Google.

### Reuse the agent in your own project

The `agent/` package is Django-free and persistence-agnostic. You can
vendor it directly (`cp -r CUTIEE/agent ~/myproject/cutiee_agent`) or
pip install the parent package. See `agent/README.md` for the standalone
import surface and `examples/standalone_cu_run.py` for a 50-line working
demo.

### Running each piece individually

```bash
# Neo4j only
./scripts/neo4j_up.sh

# Apply Cypher constraints
uv run python -m agent.persistence.bootstrap

# Django dev server
uv run python manage.py runserver

# llama-server (Qwen) on :8001
./scripts/start_llama_server.sh

# Demo Flask sites (5001, 5002, 5003) for end-to-end agent testing
uv run python scripts/start_demo_sites.py

# Cost benchmark
uv run python scripts/benchmark_costs.py --scenario all
```

### Tests

```bash
# Fast tests only (skip live Qwen and live Neo4j)
uv run pytest -m "not slow and not local and not production and not integration"

# Everything (requires Neo4j + llama-server up)
uv run pytest
```

## Where the AI feature lives

The AI feature is the agent itself. It enters the application at:

1. `apps/tasks/services.runTaskForUser` — the Django bridge.
2. `apps/tasks/runner_factory.buildLiveCuRunnerForUser` — wires browser + memory + replay + screenshot sink.
3. `agent/harness/computer_use_loop.ComputerUseRunner.run` — the screenshot ↔ function-call loop.
4. `agent/routing/models/gemini_cu.GeminiComputerUseClient.nextAction` — the model call.

Open `/tasks/` to submit a task, click "Run task now" on a task detail
page to trigger the agent, and watch the live HTMX progress + audit log.

The cost dashboard lives at `/tasks/dashboard/`. The memory bullet view
is at `/memory/`. The audit log is at `/audit/`.

## Project structure

```
CUTIEE/
├── cutiee_site/         Django project (settings, urls, sessions backend)
├── apps/
│   ├── accounts/        allauth + Neo4j auth backend
│   ├── tasks/           task submission, services bridge, runner_factory, JSON API, HTMX views
│   ├── memory_app/      ACE bullet + template dashboard, JSON export
│   ├── audit/           paginated audit log + Neo4j screenshot store
│   └── landing/         marketing landing page
├── agent/
│   ├── harness/         state, config, env_utils, computer_use_loop (the only runner)
│   ├── browser/         Playwright controller (pixel actions), env-aware factory
│   ├── memory/          ACE memory + reflector / quality_gate / curator / pipeline / replay / semantic
│   ├── routing/         models/gemini_cu (real + mock CU clients) — the only routing module
│   ├── safety/          risk classifier, approval gate, audit writer
│   └── persistence/     Neo4j driver, Cypher repos, bootstrap
├── demo_sites/          three Flask test targets (spreadsheet, slides, form)
├── scripts/             dev.sh, neo4j_up.sh, capture_storage_state.py, benchmark_costs.py
├── docs/                Part-1 product refinement, technical report, evaluation
├── static/css/          unified design tokens (cutiee.css)
├── templates/           base.html + allauth overrides
├── tests/               pytest unit + integration tests
└── render.yaml          Render deployment (single web service; progress cached in AuraDB)
```

## Environment variables

`.env.example` is the canonical reference (single source of truth — replaced
the legacy `.env.cutiee.template`). Required keys:

| Key | Required when | Purpose |
|---|---|---|
| `CUTIEE_ENV` | always | `local` or `production` |
| `DJANGO_SECRET_KEY` | always | Django session signing |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | always | Google OAuth |
| `NEO4J_BOLT_URL`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | always | Neo4j domain DB |
| `GEMINI_API_KEY` | production | Gemini Flash with the ComputerUse tool |
| `CUTIEE_CU_MODEL` | optional | Override default `gemini-flash-latest`; pin to `gemini-3-flash-preview` for deterministic replay |
| `CUTIEE_BROWSER_HEADLESS` | optional | `true` for CI; default `false` (visible browser) |
| `CUTIEE_STORAGE_STATE_PATH` | optional | Path to a Playwright storage_state.json so CU runs are pre-authenticated |
| `CUTIEE_BROWSER_CDP_URL` | optional | Attach to your real Chrome via `--remote-debugging-port=9222` instead of launching a fresh chromium |
| `CUTIEE_PROGRESS_BACKEND` | production multi-worker | `memory`, `redis`, or `neo4j` (default `memory`; demo deploys use `neo4j`) |
| `REDIS_URL` | only when `CUTIEE_PROGRESS_BACKEND=redis` | Render Redis URL |
| `CUTIEE_CU_BACKEND` | optional | `gemini` (default) or `browser_use`; both use `GEMINI_API_KEY` |
| `CUTIEE_NOVNC_URL` | optional | Public URL of the Docker worker's noVNC viewer for the live panel |
| `CUTIEE_MAX_COST_USD_PER_TASK` | optional | Wallet cap per task (default 0.50) |
| `CUTIEE_MAX_COST_USD_PER_HOUR` | optional | Wallet cap per hour (default 5.00) |
| `CUTIEE_MAX_COST_USD_PER_DAY` | optional | Wallet cap per day (default 1.00) |

## Deploy to Render

`render.yaml` is a single-service blueprint: one Python web dyno with the
cross-process progress cache stored on AuraDB (the database we already
pay for) via `CUTIEE_PROGRESS_BACKEND=neo4j`. Push to GitHub, point
Render at the repo, fill in the secrets marked `sync: false`, and the
rest provisions automatically. To opt into a Redis-backed progress cache
instead, set `CUTIEE_PROGRESS_BACKEND=redis`, add a managed Redis
service block to `render.yaml`, and wire `REDIS_URL` via `fromService`.

Detailed walkthrough in `docs/evaluation/production_readiness.md`.

## Documentation

- `docs/part1_product_refinement.md` — INFO490 Part 1 deliverable
- `docs/technical_report.md` — full architecture and design decisions
- `docs/evaluation/test_cases.md` — Part 4.1
- `docs/evaluation/failure_analysis.md` — Part 4.2
- `docs/evaluation/improvement.md` — Part 4.3
- `docs/evaluation/cost_comparison.md` — Part 4.4
- `docs/evaluation/production_readiness.md` — Part 4.5
- `README_AI.md` — AI workflow, model selection, design decisions

## License

Educational use, INFO490 Spring 2026.
