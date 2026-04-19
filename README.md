# CUTIEE

**Computer Use Token-efficient agentIc self-Evolving Engineering**

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
- llama.cpp (`brew install llama.cpp` on macOS) for local Qwen3.5

### Local setup

```bash
git clone https://github.com/Edward-H26/CUTIEE.git
cd CUTIEE
uv sync
uv run playwright install chromium

# Copy the env template and fill in values
cp .env.cutiee.template .env
# CUTIEE_ENV=local, NEO4J_*, GOOGLE_CLIENT_ID/SECRET, optional GEMINI_API_KEY

# Start Neo4j (local) + the Qwen llama-server + Django (one shot)
./scripts/dev.sh
```

The dev script starts Neo4j in Docker, downloads the Qwen GGUF if needed,
launches `llama-server` in the background on port 8001, and runs
`manage.py runserver` in the foreground on port 8000. The UI surfaces
"Warming up Qwen3.5 0.8B…" until the model responds.

Open http://localhost:8000 . Sign in with Google.

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
2. `agent/harness/orchestrator.Orchestrator.runTask` — the loop.
3. `agent/routing/router.AdaptiveRouter.routeAndPredict` — the model call.

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
│   ├── tasks/           task submission, services bridge, JSON API, HTMX views
│   ├── memory_app/      ACE bullet + template dashboard, JSON export
│   ├── audit/           paginated audit log
│   └── landing/         marketing landing page
├── agent/
│   ├── harness/         state, config, orchestrator
│   ├── browser/         Playwright controller, DOM extractor
│   ├── memory/          ACE memory + reflector / quality_gate / curator / pipeline / replay / semantic
│   ├── pruning/         RecencyPruner, fg/bg budgets, summarizer
│   ├── routing/         AdaptiveRouter, factory, difficulty + confidence probes, tier clients
│   ├── safety/          risk classifier, approval gate, audit writer
│   └── persistence/     Neo4j driver, Cypher repos, bootstrap
├── demo_sites/          three Flask test targets (spreadsheet, slides, form)
├── scripts/             dev.sh, neo4j_up.sh, start_llama_server.sh, benchmark_costs.py
├── docs/                Part-1 product refinement, technical report, evaluation
├── static/css/          unified design tokens (cutiee.css)
├── templates/           base.html + allauth overrides
├── tests/               pytest unit + integration tests
└── render.yaml          Render deployment (web + redis)
```

## Environment variables

`.env.cutiee.template` is the canonical reference. Required keys:

| Key | Required when | Purpose |
|---|---|---|
| `CUTIEE_ENV` | always | `local` or `production` |
| `DJANGO_SECRET_KEY` | always | Django session signing |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | always | Google OAuth |
| `NEO4J_BOLT_URL`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | always | Neo4j domain DB |
| `QWEN_SERVER_URL` | local | Local llama-server URL |
| `GEMINI_API_KEY` | production | Gemini 3.1 |
| `GEMINI_MODEL_TIER1/2/3` | production | Gemini variant per tier |
| `CUTIEE_PROGRESS_BACKEND` | production multi-worker | `redis` |
| `REDIS_URL` | production | Render Redis URL |
| `CUTIEE_CREDENTIAL_KEY` | optional | Fernet key for credential bullets |

## Deploy to Render

`render.yaml` describes a two-service blueprint: a Python web service and
a managed Redis. Push to GitHub, point Render at the repo, fill in the
secrets marked `sync: false`, and the rest provisions automatically.

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
