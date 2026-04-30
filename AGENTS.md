# CUTIEE — Codex Briefing

**Computer Use agentIc-framework with Token-efficient harnEss Engineering**

A Django web application that wraps a computer-use agent with three cost-reduction mechanisms and a self-evolving memory subsystem. Ships as the INFO490 A10 final assignment.

## Architecture at a glance

- `cutiee_site/`: Django project (settings, root urls, WSGI, ASGI, Neo4j session backend, `/health/` liveness endpoint)
- `apps/accounts/`: allauth Google OAuth + Neo4j-backed auth backend
- `apps/tasks/`: Task submission UI, services layer, JSON API, HTMX progress, Chart.js dashboard
- `apps/memory_app/`: Procedural/semantic/episodic bullet dashboard, template export
- `apps/audit/`: Paginated audit trail view
- `apps/landing/`: Unauthenticated landing page (miramemoria-styled)
- `apps/common/`: Cross-app shared helpers. `query_utils.safeInt` handles untrusted HTTP query-param integers with bounds clamping; every Django view that parses an int query param should reach for it instead of rolling its own try/except
- `agent/harness/`: Agent state dataclasses, config, env_utils (`envInt`/`envFloat`/`envBool`/`envStr`), `url_utils.hostFromUrl` (shared hostname extractor that strips scheme, port, and userinfo), `ComputerUseRunner` (the only runner)
- `agent/browser/`: Playwright controller (pixel-coordinate actions), env-aware factory, CDP attach
- `agent/memory/`: ACE memory (three-strength bullets, Reflect → Gate → Curate → Apply)
- `agent/routing/`: Just `models/gemini_cu` — real + mock CU clients
- `agent/safety/`: Risk classifier (word-boundary keyword match), approval gate, audit writer
- `agent/persistence/`: Neo4j driver, `run_query` / `run_single` helpers, idempotent bootstrap, health probe
- `apps/tasks/runner_factory.py`: Builds `ComputerUseRunner` (live or mock) for the services layer
- `apps/audit/screenshot_store.py`: Per-step PNG store in Neo4j with 3-day TTL
- `demo_sites/`: Flask test targets (spreadsheet, slides, form wizard)
- `scripts/`: dev.sh, neo4j_up.sh, capture_storage_state.py, benchmark_costs.py

**Where shared helpers live.** Follow these conventions when adding new utilities:

- HTTP query-param parsing, request validation, and other Django view helpers go in `apps/common/`
- Agent-internal utilities with no Django dependency (URL parsing, env parsing, text slug helpers) go in `agent/harness/` alongside `env_utils.py` and `url_utils.py`
- Domain-scoped Cypher queries stay in `apps/<app>/repo.py` so data access remains per-app (do not consolidate them into a global repo)

## Runtime split via `CUTIEE_ENV`

| `CUTIEE_ENV` | Agent client | Database |
|--------------|--------------|----------|
| `local` | `MockComputerUseClient` + `StubBrowserController` (offline scripted demo) | Neo4j 5 in Docker on bolt://localhost:7687 |
| `production` | `GeminiComputerUseClient` (`gemini-flash-latest` default) + real Chromium | Neo4j AuraDB Free on neo4j+s://... |

CUTIEE has **one runner**: `ComputerUseRunner` (screenshot + pixel coordinates).
The DOM-router stack (AdaptiveRouter / GeminiCloudClient / DOMState extraction /
`Orchestrator`) was removed in 2026-04 once Gemini Flash gained the ComputerUse
tool at flash pricing. `agent/pruning/context_window.py:RecencyPruner` survived
that sweep because Phase 13 still uses it to trim Gemini CU history to
`CUTIEE_HISTORY_KEEP_TURNS` turns. Local mode is now MockCU only, there is no
offline Gemini equivalent, so true browser automation requires a Gemini key.

Override the CU model via `CUTIEE_CU_MODEL=<id>` in `.env`. Verified-supported ids:
`gemini-flash-latest` (default, auto-upgrade), `gemini-3-flash-preview` (pinned),
`gemini-2.5-computer-use-preview-10-2025` (specialty preview, ~8× pricing).
Anything else risks a 400 "Computer Use is not enabled" from Google.

Unset or invalid `CUTIEE_ENV` raises `RuntimeError` at settings import. No silent fallback.

## CU Backend Selection

`CUTIEE_CU_BACKEND` picks between two equivalent CU paths:

| Backend | Model | Credential |
|---------|-------|------------|
| `gemini` (default) | `gemini-flash-latest` (override via `CUTIEE_CU_MODEL`) | `GEMINI_API_KEY` |
| `browser_use` | `gemini-3-flash-preview` (fixed) | `GEMINI_API_KEY` |

Both paths share the same credential because `browser-use` is wired to Gemini 3 Flash in this project. An unknown value raises consistent with the no-silent-fallback policy. Install the browser-use extra with `pip install "cutiee[browser_use]"` or `uv sync --group browser_use` before using that backend.

Adapters translate native actions into the canonical `ActionType` enum so the replay planner at `agent/memory/replay.py` can round-trip procedural bullets across backends. Native debugging metadata rides inside `Action.reasoning` as JSON behind a `__adapter_meta__{...}__` marker so consumers that care can parse it and consumers that do not see a longer reasoning string. The audit schema is unchanged.

## Runtime Env Vars Added

| Var | Default | Purpose |
|-----|---------|---------|
| `CUTIEE_CU_BACKEND` | `gemini` | Selects `gemini` or `browser_use`. |
| `CUTIEE_MAX_COST_USD_PER_TASK` | `0.50` | Phase 4 per-task wallet cap. |
| `CUTIEE_MAX_COST_USD_PER_HOUR` | `5.00` | Phase 4 per-hour wallet cap, enforced via Neo4j `:CostLedger`. |
| `CUTIEE_HISTORY_KEEP_TURNS` | `8` | Phase 13 context-trim knob for Gemini CU history. |
| `CUTIEE_REPLAY_FRAGMENT_CONFIDENCE` | `0.80` | Phase 11 per-fragment confidence threshold. |
| `CUTIEE_ALLOW_URL_FRAGMENTS` | `0` | Phase 5 opt-in to preserve `#...` URL fragments instead of stripping them before `NAVIGATE`. |

## Neo4j Node Types Introduced

- `:CostLedger {user_id, hour_key, hourly_usd}` for Phase 4 per-hour wallet tracking.
- `:PreviewApproval {execution_id, user_id, status, summary}` for Phase 16 pre-run preview, plus the user-facing approve/cancel flow wired through `apps/tasks/preview_queue.py` and `apps/tasks/api.py`.
- `:Screenshot {execution_id, step_index, data_b64, size_bytes, created_at}` per-step PNG store in `apps/audit/screenshot_store.py`, with a composite uniqueness constraint on `(execution_id, step_index)` and a 3-day TTL sweep.

The action-approval flow is in-process only; `apps/tasks/approval_queue.py` parks the runner on an `asyncio.Event` and writes nothing to Neo4j, so there is no matching node label. Converting it to a Neo4j-backed queue would require re-adding a `:ActionApproval` constraint in `agent/persistence/bootstrap.py`.

Bootstrap via `python -m agent.persistence.bootstrap` to install the new constraints and indexes; it is idempotent.

## Memory model (ACE)

Every piece of remembered knowledge is a `Bullet` with three strength channels: semantic, episodic, procedural. Per-channel exponential decay with different rates (semantic 0.01, episodic 0.05, procedural 0.002). Retrieval ranks by `0.60 * relevance + 0.20 * total_strength + 0.20 * type_priority` with a "keep at least 2 learned bullets" post-filter. The self-evolving loop is `Reflector → QualityGate(≥0.60) → Curator → apply_delta → refine`.

Ported from:
- miramemoria: `app/services/neo4j_memory.py`, `app/chat/ace_runtime.py`, `app/chat/decay.py`
- LongTermMemoryBasedSelfEvolvingAlgorithm: `src/ace_memory.py`, `src/ace_components.py`

## Coding conventions

- Double quotes for all strings
- Spaces around operators (`x = 1`, `a + b`)
- Comments only on important or non-obvious functions; no comments on self-explanatory code
- No `print` / `console.log` in production code
- Type hints everywhere
- camelCase for variables and functions; PascalCase for classes and Neo4j node labels; UPPER_SNAKE_CASE for constants
- Boolean names start with `is`, `has`, or `should`
- Dataclasses over dicts inside `agent/`
- Cypher-backed repos under `apps/*/repo.py` for all persisted data (no Django ORM for domain models)
- Never run `git commit` or `git push` — the user is the sole author
- No `Co-Authored-By` in commits
- Em dashes and en dashes are forbidden in prose; use commas or restructure

## Testing philosophy

Targeted checks before full-suite checks. TDD for every new component in `agent/` — failing test first, minimal implementation, passing test, next task. Mark slow/live-env tests with pytest markers so CI can exclude them.

## Failure policy

No silent fallbacks. Missing dependencies, missing model files, missing API keys, unset `CUTIEE_ENV`, an unreachable Neo4j bolt endpoint, or unreachable VLM servers all raise a clear error with actionable remediation. The user picks the model and the database explicitly.

## Reference

The canonical runtime specification is `SPEC.md`. Active implementation plans live under `plans/`; currently `plans/linear-cuddling-nygaard.md` is the working plan. `REVIEW.md` tracks open refactor findings. `DEPLOY-RENDER.md` is the production deployment guide.
