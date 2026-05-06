# CUTIEE

**Computer Use agentIc-framework with Token-efficient harnEss Engineering**

A Django web application that wraps a computer-use agent with three
cost-reduction mechanisms (procedural memory replay, temporal recency
pruning, and hybrid local memory-side inference) and a self-evolving
memory subsystem. Recurring tasks drop to zero VLM cost; novel browser
actions run through Gemini Flash Computer Use while memory reflection,
retrieval, replay matching, and safety checks stay local where possible.

INFO490 final project (A10).

## What it does

- Submit a natural-language task (for example, "sort my Sheets by column B").
- The agent checks procedural memory first. If a learned workflow matches
  above the similarity threshold, the planner reconstructs the action
  sequence and the browser controller replays it through Playwright at
  zero inference cost.
- If no replay path exists, the orchestrator runs the observe-reason-act
  loop. The pruner trims the trajectory before each model call, Gemini
  Flash emits the browser action, and the safety gate suspends high-risk
  actions for explicit user approval.
- Every step is audited. The cost dashboard plots daily spend and tier
  distribution. The memory dashboard exposes the learned bullet store
  and the procedural templates.

## AI architecture (hybrid local + API)

CUTIEE is a hybrid system. The browser-control vision-language work runs through
`gemini-flash-latest` with the Computer Use tool because no offline open-weights model
is competitive at pixel-coordinate browser control today. Every other AI step has a
real local component:

- **Memory-side LLM:** cached `Qwen/Qwen3.5-0.8B` (HuggingFace transformers, MIRA
  pattern) drives the reflector and decomposer for localhost tasks. Falls back to
  Gemini, then to a heuristic implementation if neither is available. See
  `agent/memory/local_llm.py` and `agent/memory/reflector.py:303-318`.
- **Embeddings:** `BAAI/bge-small-en-v1.5` via FastEmbed for memory retrieval and
  procedural replay matching, with a SHA-256 hash fallback for tests / offline.
- **Risk classification, curator, quality gate, decay, replay planner, cost wallet,
  preview generation:** all local, no model.

Full model selection rationale, per-step pipeline, fallback chains, and an API-only
comparison live in [`README_AI.md`](./README_AI.md). The runtime contract is in
[`SPEC.md`](./SPEC.md).

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

# Recommended for CUTIEE_ENV=local: pre-cache the Qwen 3.5 0.8B weights
# so the memory-side reflector loads in roughly 2 seconds instead of 10.
# Requires the optional local_llm dep group; safe to skip in production.
uv sync --group local_llm
uv run python scripts/cache_local_qwen.py

# Start Neo4j (local) + Django (one shot)
./scripts/dev.sh
```

The dev script starts Neo4j in Docker and runs `manage.py runserver` on
port 8000. With `CUTIEE_ENV=local` the agent uses `MockComputerUseClient`
(scripted demo actions, no API calls). With `CUTIEE_ENV=production` and a
`GEMINI_API_KEY`, every task runs through the live Gemini Computer Use tool.

Open http://localhost:8000 . Sign in with Google.

Local Qwen cache:
Install `uv sync --group local_llm` if you want the localhost dev stack to
use `Qwen/Qwen3.5-0.8B` for memory-side decomposition/lesson extraction.
On first localhost run, CUTIEE downloads the weights into
`.cache/huggingface-models/` and reuses that cache on later runs.
If you want to warm the cache ahead of time, run
`python scripts/cache_local_qwen.py`.

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

# Pre-cache Qwen3.5-0.8B for the memory-side LLM (~1.6 GB into
# .cache/huggingface-models/, gitignored). Only needed when running with
# CUTIEE_ENV=local against localhost tasks.
uv run python scripts/cache_local_qwen.py

# Demo Flask sites (5001, 5002, 5003) for end-to-end agent testing
uv run python scripts/start_demo_sites.py

# Cost benchmark
uv run python scripts/benchmark_costs.py --scenario all

# Verify torch / transformers stay out of the Render base deps
bash scripts/verify_render_isolation.sh
```

### Tests

```bash
# Fast tests only (skip live Neo4j, live Qwen, and live Gemini)
uv run pytest -m "not slow and not local and not production and not integration"

# Everything (requires Neo4j up; Qwen weights cached for the local_llm tests)
uv run pytest
```

## Where the AI feature lives

The AI feature is the agent itself. It enters the application at:

1. `apps/tasks/services.runTaskForUser`: the Django bridge.
2. `apps/tasks/runner_factory.buildLiveCuRunnerForUser`: wires browser, memory, replay, and the screenshot sink.
3. `agent/harness/computer_use_loop.ComputerUseRunner.run`: the screenshot ↔ function-call loop.
4. `agent/routing/models/gemini_cu.GeminiComputerUseClient.nextAction`: the model call.

Open `/tasks/` to submit a task, click "Run task now" on a task detail
page to trigger the agent, and watch the live HTMX progress + audit log.

The cost dashboard lives at `/tasks/dashboard/`. The memory bullet view
is at `/memory/`. The audit log is at `/audit/`.

## Project structure

```
CUTIEE/
├── cutiee_site/         Django project (settings, urls, sessions backend)
├── apps/
│   ├── accounts/        local allauth path + production Neo4j auth backend
│   ├── common/          cross-app helpers (query_utils.safeInt, future request validators)
│   ├── tasks/           task submission, services bridge, runner_factory, JSON API, HTMX views
│   ├── memory_app/      ACE bullet + template dashboard, JSON export
│   ├── audit/           paginated audit log + Neo4j screenshot store
│   └── landing/         marketing landing page
├── agent/
│   ├── harness/         state, config, env_utils, url_utils (hostFromUrl), computer_use_loop (the only runner)
│   ├── browser/         Playwright controller (pixel actions), env-aware factory
│   ├── memory/          ACE memory + reflector / quality_gate / curator / pipeline / replay / semantic
│   ├── routing/         models/gemini_cu (real + mock CU clients), the only routing module
│   ├── safety/          risk classifier (word-boundary keywords), approval gate, audit writer
│   └── persistence/     Neo4j driver, Cypher repos, bootstrap, health probe
├── demo_sites/          three Flask test targets (spreadsheet, slides, form)
├── scripts/             dev.sh, neo4j_up.sh, capture_storage_state.py, benchmark_costs.py
├── static/css/          unified design tokens (cutiee.css)
├── templates/           base.html + account templates
├── tests/               pytest unit + integration tests
├── render.yaml         Render Blueprint: CUTIEE (Django) + cutiee-worker (Dockerized Xvfb + Chromium + noVNC)
└── Dockerfile.worker   Worker image for the live framebuffer service
```

## Environment variables

`.env.example` is the canonical reference (single source of truth; replaced
the legacy `.env.cutiee.template`). Required keys:

| Key | Required when | Purpose |
|---|---|---|
| `CUTIEE_ENV` | always | `local` or `production` |
| `DJANGO_SECRET_KEY` | always | Django session signing |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | always | Google OAuth |
| `NEO4J_BOLT_URL`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | always | Neo4j domain DB |
| `GEMINI_API_KEY` | production | Gemini Flash with the ComputerUse tool |
| `CUTIEE_NEO4J_FRAMEWORK_AUTH` | production | Default `true`; stores production auth, sessions, and preferences in Neo4j instead of Django SQL |
| `CUTIEE_CU_MODEL` | optional | Override default `gemini-flash-latest`; pin to `gemini-3-flash-preview` for deterministic replay |
| `CUTIEE_ENABLE_LOCAL_LLM` | optional | Default `true`; when `CUTIEE_ENV=local` and the task targets `localhost` or `127.0.0.1`, prefer cached `Qwen/Qwen3.5-0.8B` for memory-side JSON generation |
| `CUTIEE_LOCAL_LLM_CACHE_DIR` | optional | Override the Hugging Face cache root (default `.cache/huggingface-models/`) |
| `CUTIEE_BROWSER_HEADLESS` | optional | `true` for CI; default `false` (visible browser) |
| `CUTIEE_STORAGE_STATE_PATH` | optional | Path to a Playwright storage_state.json so CU runs are pre-authenticated |
| `CUTIEE_BROWSER_CDP_URL` | optional | Attach to your real Chrome via `--remote-debugging-port=9222` instead of launching a fresh chromium |
| `CUTIEE_BROWSER_CDP_HOST` | production Blueprint | Render private hostname for `cutiee-worker`; combined with `CUTIEE_BROWSER_CDP_PORT` |
| `CUTIEE_BROWSER_CDP_PORT` | production Blueprint | Chrome DevTools port on the worker, normally `9222` |
| `CUTIEE_PROGRESS_BACKEND` | optional local/debug override | Production defaults to `neo4j`; local/tests default to `memory`; `redis` requires `REDIS_URL` |
| `REDIS_URL` | only when `CUTIEE_PROGRESS_BACKEND=redis` | Render Redis URL |
| `CUTIEE_CU_BACKEND` | optional | `gemini` (default) or `browser_use`; both use `GEMINI_API_KEY` |
| `CUTIEE_WORKER_EXTERNAL_URL`, `CUTIEE_WORKER_EXTERNAL_HOSTNAME` | production Blueprint | Public worker values used to derive `/vnc.html` for the live panel |
| `CUTIEE_NOVNC_URL` | production Blueprint | noVNC viewer URL; current demo default is `https://cutiee-worker.onrender.com/vnc.html` |
| `CUTIEE_MAX_COST_USD_PER_TASK` | optional | Wallet cap per task (default 0.50) |
| `CUTIEE_MAX_COST_USD_PER_HOUR` | optional | Wallet cap per hour (default 5.00) |
| `CUTIEE_MAX_COST_USD_PER_DAY` | optional | Wallet cap per day (default 1.00) |

## Deploy to Render

`render.yaml` is a two-service Blueprint:

- `CUTIEE`: Python web dyno running Django + HTMX. Drives a remote
  Chromium over CDP; never launches a browser in-process.
- `cutiee-worker`: Docker image built from `Dockerfile.worker`. Runs
  Xvfb, fluxbox, x11vnc, websockify, and a headed Chromium. Serves
  noVNC publicly on port 6080 so the dashboard can embed it in an
  iframe; exposes Chromium's CDP on 9222 to the private network only.

Push to GitHub, point Render at the repo once via **New +** > **Blueprint**,
and Render provisions both services in lockstep. Paste the `sync: false`
secrets during the first sync. Production auth, sessions, preferences, and
domain data are stored in Neo4j; the Blueprint sets `CUTIEE_NOVNC_URL` and
also derives the worker's public URL/hostname when Render exposes them.

Cross-process progress defaults to AuraDB whenever `CUTIEE_ENV=production`,
so no Redis dyno or progress env var is required. The blueprint also pins
every runtime tunable that is environment-specific (cost caps, CU model,
history window) so the two services stay in sync automatically; override by
editing `render.yaml`, not the dashboard.

Full walkthrough: `DEPLOY-RENDER.md` at the repo root.

## INFO490 A10 deliverables map

The submission ships several documents at different lengths so the grader can pick the right one for each rubric category. The page-bounded rubric deliverable is `docs/REPORT.pdf`; the others provide depth, standalone Part 1, and supporting evidence.

| Rubric expectation | File | Length | Purpose |
|---|---|---|---|
| Technical Report PDF (4-6 pages) | [`docs/REPORT.pdf`](./docs/REPORT.pdf) | 5 pages | The rubric-graded submission. Covers Product Overview, Django System Architecture, AI Integration, Evaluation and Failure, Cost and Production Readiness. |
| Part 1 write-up (1-2 pages) | [`docs/PART1.md`](./docs/PART1.md) | ~2 pages | Standalone refined problem statement, target users, final feature set, user flow, system flow diagram. |
| Verbose technical appendix | [`docs/TECHNICAL-REPORT.pdf`](./docs/TECHNICAL-REPORT.pdf) | 27 pages | Reference document with full architecture detail, mermaid diagrams, deployment topology, and SLO tables. |
| Academic preprint | [`docs/paper/cutiee_icml2026.pdf`](./docs/paper/cutiee_icml2026.pdf) | 4 pages | ICML-style preprint with literature citations and the production cost narrative. |
| Evaluation tables (8 cases) | [`docs/EVALUATION.md`](./docs/EVALUATION.md) | - | Input, Expected, Actual, Quality, Latency per rubric Section 4.1. |
| Failure post-mortems (4 failures) | [`docs/FAILURES.md`](./docs/FAILURES.md) | - | Root cause, evidence, mitigation per rubric Section 4.2. |
| Improvements (3 deltas) | [`docs/IMPROVEMENT.md`](./docs/IMPROVEMENT.md) | - | Before-and-after metrics per rubric Section 4.3. |
| AI integration narrative | [`README_AI.md`](./README_AI.md) | - | Workflow, model selection, design decisions, full API-only comparison. |

To rebuild the PDFs after a markdown edit:

```bash
# Rebuild the rubric-graded 5-page report
uv run python scripts/build_report_pdf.py --source docs/REPORT.md --output docs/REPORT.pdf --title "CUTIEE: Token-Efficient Computer-Use Agents in Django"

# Rebuild the verbose 27-page appendix
uv run python scripts/build_report_pdf.py
```

## Documentation

Project-level docs live at the repo root:

- `SPEC.md`: canonical runtime specification after the 17-phase integration
- `DEPLOY-RENDER.md`: production deployment walkthrough for the two-service Render Blueprint
- `REVIEW.md`: open refactor findings, tracked independently of commits
- `AUDIT-DEV-BRANCH.md`: dev-branch audit output
- `CLAUDE.md`: Claude Code briefing with coding conventions and runtime env matrix
- `agent/README.md`: the standalone agent library's API surface
- `CUTIEEDesignSystem/README.md`: design-system brand, colour, typography, and component guidance

## License

Educational use, INFO490 Spring 2026.
