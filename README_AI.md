# CUTIEE AI Integration

This document describes how AI works inside CUTIEE: where it enters the user flow, which
models we use, how inputs are processed, how outputs are returned, what guardrails sit
on each step, and why we chose a hybrid local + API design instead of relying on a single
hosted provider. Companion to `README.md` (setup) and `SPEC.md` (runtime contract).

## TL;DR

| Pipeline step | Where in code | Model | Local or API |
|---|---|---|---|
| Form submission and risk classification | `apps/tasks/forms.py:11`, `agent/safety/risk_classifier.py` | regex (word-boundary keywords) | local |
| Pre-run preview | `apps/tasks/preview_queue.py`, `agent/harness/preview.py` | rule-based template | local |
| Replay match | `agent/memory/replay.py`, `fragment_replay.py` | cosine similarity over embeddings | local |
| Embedding | `agent/memory/embeddings.py` | `BAAI/bge-small-en-v1.5` (FastEmbed) or SHA-256 hash | local |
| Browser-control loop | `agent/routing/models/gemini_cu.py` | `gemini-flash-latest` (Computer Use tool) | API |
| Action execution | `agent/browser/controller.py` | none (Playwright) | local |
| Reflector (lesson distillation) | `agent/memory/reflector.py:303-318` | `Qwen/Qwen3.5-0.8B` (localhost), `gemini-flash-latest` (otherwise), heuristic (fallback) | hybrid |
| Decomposer (action graph) | `agent/memory/decomposer.py:101-114` | `Qwen/Qwen3.5-0.8B` (localhost), `gemini-flash-latest` (otherwise), empty graph (fallback) | hybrid |
| Quality gate, curator, decay | `agent/memory/quality_gate.py`, `curator.py`, `decay.py` | threshold logic, rule-based dedup, exponential math | local |
| Cost wallet | `agent/harness/cost_ledger.py` | none | local |

CUTIEE is a hybrid system. The browser-control vision-language work is delegated to
Gemini Flash because no offline open-weights model is competitive at pixel-coordinate
Computer Use today. Every other AI step has a real local component, and the memory-side
LLM (reflector and decomposer) runs on a cached `Qwen/Qwen3.5-0.8B` for localhost
demos so the full ACE pipeline produces real lessons even with no API key set.

---

## Where AI enters the user flow

1. The user submits a natural-language task at `/tasks/` (`apps/tasks/views.py:59
   create_task`). The Django form (`apps/tasks/forms.py:11`) collects a description, an
   optional initial URL, and an optional domain hint.
2. The task is persisted to Neo4j via `apps/tasks/repo.py`. The form view redirects to
   the detail page where the user clicks "Run task now."
3. `apps/tasks/api.py:42 run_task_view` validates ownership, creates an `:Execution`
   row, and spawns a background thread that calls
   `apps/tasks/services.runTaskForUser`.
4. `runner_factory.buildLiveCuRunnerForUser`
   (`apps/tasks/runner_factory.py:57-133`) selects the CU client based on
   `CUTIEE_ENV` and `CUTIEE_CU_BACKEND`, wires the browser controller, replay planner,
   ACE memory, cost ledger, screenshot store, and approval gates.
5. The runner enters the screenshot to function-call loop in
   `agent/harness/computer_use_loop.py`. After every step it calls
   `progressCallback` which writes to Neo4j and to a process-local cache; the dashboard
   polls `/tasks/api/status/<execution_id>/` over HTMX every two seconds.
6. When the task completes (or the cost cap fires, or a heartbeat times out, or
   approval is denied), the runner finalizes the execution and runs the ACE pipeline:
   `Reflector → QualityGate → Curator → ApplyDelta`. Lessons land in Neo4j and surface
   in `/memory/` and `/audit/`.

The user only sees the dashboard. The AI machinery is deliberately invisible until the
user opens the cost dashboard at `/tasks/dashboard/` (model tier distribution, daily
spend) or the memory dashboard at `/memory/` (procedural / episodic / semantic
bullets and templates).

---

## How user input is processed

The task description passes through three stages before any model invocation:

1. **Form validation** (`apps/tasks/forms.py:11 TaskSubmissionForm`). Length capped at
   800 characters. URL field validated by Django's URLField. No model in this step.
2. **Risk classification** (`agent/safety/risk_classifier.py`). Compiled word-boundary
   regex against `HIGH_RISK_KEYWORDS` (delete, purchase, wire transfer, password, etc.)
   and `MEDIUM_RISK_KEYWORDS` (edit, update, share, etc.). Output is a tier label that
   gates the approval flow. Pure regex; no ML.
3. **Pre-run preview** (`agent/harness/preview.py`, `apps/tasks/preview_queue.py`). A
   rule-based summary of what the agent will attempt, persisted to a Neo4j
   `:PreviewApproval` node. The runner blocks on `asyncio.wait_for(..., timeout=600s)`
   until the user clicks Approve or Cancel in the dashboard. No model.

Once the user approves the preview, the agent enters the screenshot loop. Each iteration
captures a screenshot, asks Gemini "given this screenshot and the task, what action next?"
via the Computer Use tool, validates the response against the canonical `ActionType`
enum, runs the risk classifier on the action, and either fires the action through
Playwright or pauses for user approval if the risk tier requires it.

---

## Which models are used

### `gemini-flash-latest` (Google) — browser-control loop

Configured at `agent/routing/models/gemini_cu.py:74-279`. Gated by
`CUTIEE_ENV=production` and `GEMINI_API_KEY`. The Computer Use tool surface is
documented at the Gemini API reference; CUTIEE uses
`environment="ENVIRONMENT_BROWSER"`. Override the model id via
`CUTIEE_CU_MODEL=<id>` in `.env`. Pricing as of 2026-04-29: $0.15 per million input
tokens, $0.60 per million output tokens for `gemini-flash-latest`.

Why we chose Gemini for this step: no open-weights model with a Computer Use tool
surface and pixel-coordinate accuracy is currently competitive. Anthropic Computer Use
API and OpenAI Operator are the alternatives, both ~25x more expensive per task at
similar quality. The browser-control loop is the only step where we accept an API
dependency because the alternative is dropping the agent altogether.

### `Qwen/Qwen3.5-0.8B` (Hugging Face, local) — memory-side reflector and decomposer

Configured at `agent/memory/local_llm.py:27` (`MODEL_ID = envStr("CUTIEE_LOCAL_LLM_MODEL",
"Qwen/Qwen3.5-0.8B")`). Loaded via HuggingFace transformers with `AutoModelForCausalLM`
and `AutoTokenizer`. Cached on first use into `.cache/huggingface-models/` (gitignored)
through `huggingface_hub.snapshot_download` with `resume_download=True`. After warmup
every load uses `local_files_only=True` so the worker never re-hits the network.

Device probe order is CUDA → MPS → CPU (`agent/memory/local_llm.py:170-179`).
Quantization is float16 on CUDA / MPS, optionally float16 on CPU via
`CUTIEE_LOCAL_LLM_FP16_CPU=true`. Generation parameters use `do_sample=False`
(deterministic) for the reflector and decomposer because both steps emit JSON; sampled
outputs corrupt the schema too often at 0.8B parameters.

Activation predicate (`agent/memory/local_llm.py:47-55 shouldUseLocalLlmForUrl`):

```
(CUTIEE_ENABLE_LOCAL_LLM == True, default true)
AND CUTIEE_ENV == "local"
AND (CUTIEE_FORCE_LOCAL_LLM == True
     OR initialUrl host in {"localhost", "127.0.0.1"})
```

This pattern follows the [MIRA project's local LLM gating](https://github.com/Edward-H26/MIRA/blob/main/app/services/local_llm.py).
When the predicate is False the reflector / decomposer fall back to Gemini, then to a
purely heuristic implementation if no API key is set. The fallback chain is the reason
CUTIEE's memory pipeline keeps working even with zero API budget and zero local model.

Why we chose Qwen 0.8B: small enough to load on a developer laptop in under ten seconds,
strong enough to follow JSON schemas for short reflection / decomposition prompts, MIT
licensed, no telemetry. The reflector's prompt is not safety-critical so a sub-1B model
is acceptable.

### `BAAI/bge-small-en-v1.5` (Hugging Face, local) — semantic embeddings

Configured at `agent/memory/embeddings.py:67-76`. Loaded lazily via FastEmbed
(`fastembed>=0.3` in base deps). The model is a 384-dimensional MiniLM-style embedder
(33M parameters, ~70 MB on disk). Used by:

- `agent/memory/ace_memory.py:88` for query relevance scoring during retrieval
- `agent/memory/replay.py` for procedural template matching
- `agent/memory/fragment_replay.py:25-27` for fragment-level replay scoring
- `agent/memory/curator.py:74` for embedding-similarity-based dedup (≥0.90 threshold)

A SHA-256 hash-based fallback (`agent/memory/embeddings.py:41-52 hashEmbedding`) covers
the offline / test path. The hash embedding has no semantic structure but produces
stable cosine values for ranking math.

### Heuristic reflector and rule-based curator (no model)

Default reflector is `agent/memory/reflector.py HeuristicReflector` which walks
successful steps and emits procedural / episodic / semantic lessons deterministically.
Curator (`agent/memory/curator.py:35-90`) is rule-based: hash-or-cosine dedup, strength
boosts on accept, supersession on conflict. No ML in either step.

---

## How outputs are generated and returned

The screenshot loop returns a sequence of `Action` dataclasses, each with a target,
optional value, optional coordinate, optional keys, a confidence score, and a free-text
reasoning field. Actions go through:

1. The risk classifier (`agent/safety/risk_classifier.py`).
2. The approval gate (`agent/safety/approval_gate.py:37-58`). High-risk actions block
   on an `asyncio.Event` until the user clicks Approve or Reject in the modal that the
   dashboard polls via HTMX.
3. The cost wallet (`agent/harness/cost_ledger.py`). Per-task, per-hour, and per-day
   USD caps enforced via Neo4j `:CostLedger` MERGE.
4. The browser controller (`agent/browser/controller.py`). Playwright executes the
   pixel action.
5. The progress publisher writes the step to Neo4j (`:ObservationStep` linked from
   `:Execution`) plus an audit screenshot (`:Screenshot` with 3-day TTL).

The dashboard polls `/tasks/api/status/<execution_id>/` (`apps/tasks/api.py:99`) which
returns a JSON snapshot. HTMX swaps the rendered partial in place. When the loop
completes, the runner persists the final outcome (`completionReason`) and triggers
the ACE pipeline. Memory bullets show up in the `/memory/` dashboard and procedural
templates surface as replay candidates on the next run of a similar task.

---

## Guardrails

| Concern | Mechanism | File |
|---|---|---|
| Invalid task input | Form validation, URL scheme check | `apps/tasks/forms.py:11` |
| Out-of-budget run | Per-task / per-hour / per-day cost caps | `agent/harness/cost_ledger.py:37-104` |
| Dangerous action | Word-boundary regex risk classifier + approval gate | `agent/safety/risk_classifier.py`, `agent/safety/approval_gate.py` |
| Stalled run | Heartbeat silence detector | `agent/harness/heartbeat.py` |
| Auth-gated page | URL pattern detection, ends with `auth_expired` | `agent/harness/computer_use_loop.py` |
| CAPTCHA | Visual screenshot detector | `agent/safety/captcha_detector.py` |
| Prompt injection | Pre-model injection guard | `agent/safety/injection_guard.py` |
| Sensitive content in lessons | Credential redaction (CC, SSN, CVV regex) | `agent/memory/reflector.py:73-90` |
| Sensitive content in screenshots | Text-bullet redaction live; visual DOM probe is staged work | `apps/audit/screenshot_store.py`, planned Playwright probe |
| Plan drift mid-run | URL-loose-match check, mid-run re-approval (Phase 17) | `agent/harness/computer_use_loop.py`, `SPEC.md:136-138` |
| Cost ledger leak | Per-user `user_id` constraint on `:CostLedger` and `:MemoryBullet` | `agent/persistence/bootstrap.py` |
| Local model outage | Fallback chain Qwen → Gemini → Heuristic | `agent/memory/reflector.py:303-318` |

---

## API comparison

### What an API-only version would look like

The minimal API-only design uses Anthropic's Computer Use API or OpenAI's Operator and
delegates the entire task end-to-end. Memory and replay run on the provider's
infrastructure or are absent. There is no local model and no per-user cost ceiling
beyond the org-wide billing. The UI becomes a thin wrapper around the provider's
session API.

### Why CUTIEE does not pick that

| Dimension | API-only baseline | CUTIEE | Evidence |
|---|---|---|---|
| Cost on recurring tasks | ~$0.0115 per 15-step task (Gemini Flash naive cloud) | $0 (procedural replay tier 0) | `scripts/benchmark_costs.py` cutiee_replay scenario |
| Cost on novel tasks | $0.0115 baseline | ~$0.0046 (60% saving via tier mix) | `scripts/benchmark_costs.py` cutiee_first_run scenario |
| Cost on memory-side LLM (per task) | ~$0.001-0.005 per reflector / decomposer call | $0 on localhost (Qwen3.5-0.8B local) | `agent/memory/local_llm.py`, `agent/memory/reflector.py:307` |
| Per-user budget control | Hosted org-wide billing | Per-task / per-hour / per-day Neo4j ledger | `agent/harness/cost_ledger.py` |
| Audit transparency | Varies; usually opaque | Every screenshot + step persisted, 3-day TTL | `apps/audit/screenshot_store.py`, Neo4j `:Screenshot` |
| Privacy | Provider sees all input and output | Reflector redacts credentials; on localhost, Qwen runs offline so reflection content never leaves the developer machine | `agent/memory/reflector.py:73-90`, `agent/memory/local_llm.py` |
| Data export | Usually none | `/memory/export/` JSON attachment | `apps/tasks/api.py:186` |
| Backend swap | Provider lock-in | One env var: `CUTIEE_CU_BACKEND=gemini` or `browser_use` | `apps/tasks/runner_factory.py:170` |
| Offline demo | Impossible | Full memory pipeline plus mock CU works without network | mock CU + cached Qwen + hash embeddings |
| Failure recovery | Provider retry behavior | Three-tier fallback (Qwen → Gemini → heuristic) for memory; `MockComputerUseClient` for CU loop | `agent/memory/reflector.py:312-318` |

### Validating the cost claim against external benchmarks

CUTIEE inherits the ACE memory architecture validated in
`https://github.com/Edward-H26/LongTermMemoryBased-ACE/blob/main/benchmark/results/v5/comparison_report_v5.md`.
That study compared GPT-5.1 (High) Baseline against the same model with ACE memory
across 200 CL-bench tasks:

| Metric | Baseline | ACE | Delta |
|---|---|---|---|
| Overall solving rate | 19.5% | 23.0% | +17.9% |
| Procedural task execution (n=47) | 14.9% | 25.5% | +71.4% |
| Rule system application (n=62) | 25.8% | 33.9% | +31.2% |
| Domain knowledge reasoning (n=85) | 17.6% | 14.1% | -20.0% |
| Avg tokens / task | 11,045 | 44,516 | +303% |
| Estimated cost | $6.84 | $169.32 | +12x |

ACE memory adds quality (especially on procedural tasks, the category most relevant to
CUTIEE's browser workflows) at a 12x cost penalty. CUTIEE's contribution on top of
vanilla ACE is the cost-mitigation layer:

- **Procedural replay** sets cost to $0 on cached recurring tasks (`cutiee_replay`
  scenario, 100% saving versus naive cloud).
- **Local Qwen3.5-0.8B for the reflector / decomposer auxiliary path** eliminates the
  +$122.79 auxiliary cost component for localhost demos.
- **Multi-tier model routing** (replay tier 0 plus Gemini Flash variants) lands a 60%
  saving on the first run of novel tasks.

Net result: keep most of the +17.9% quality uplift while dropping the +12x cost penalty
to single-digit savings on recurring tasks.

---

## Why we chose this hybrid design

| Design choice | Rationale |
|---|---|
| Gemini Flash for the CU loop | No competitive offline equivalent for screenshot Computer Use today |
| Qwen3.5-0.8B for memory-side LLM | Small enough to fit on a laptop; deterministic JSON output via `do_sample=False`; MIT license; matches the [MIRA project pattern](https://github.com/Edward-H26/MIRA) |
| FastEmbed for embeddings (when enabled) | 70 MB on disk, CPU-friendly, MTEB-validated for retrieval |
| Hash embedding fallback | Test mode and offline mode work without any model |
| Reflector / decomposer fallback chain | Qwen 0.8B occasionally emits malformed JSON; Gemini fallback is the safety net; heuristic is the floor |
| Per-channel decay (semantic 0.01, episodic 0.05, procedural 0.005) | Procedural workflows are highest-value, episodic context is lowest-value; rates reflect that ordering |
| Three-tier replay (whole template, fragment, model) | Whole-template hits zero-cost replay; fragment hits partial-cost interleave; model hits full Gemini call only for novel decisions |
| Local Qwen gated to `localhost` URLs | Most demo workflows run against `localhost:5001/5002/5003` Flask sites; gating here makes Qwen a real production-runtime concern only when the dev intends it |

---

## Reproduction

```bash
# Pre-cache Qwen weights (one-time, ~1.6 GB)
uv run python scripts/cache_local_qwen.py

# Verify torch / transformers are NOT in the Render base deps
bash scripts/verify_render_isolation.sh

# Run the local Qwen unit tests (does not load the real model; uses monkeypatch)
uv run pytest tests/agent/test_local_llm.py -v

# Run the cost benchmark
uv run python scripts/benchmark_costs.py --scenario all

# Run the local memory eval (3 demo Flask sites required)
uv run python scripts/start_demo_sites.py     # in one terminal
uv run python -m agent.eval.webvoyager_lite --backend gemini --scenario all
```

---

## Production deployment

CUTIEE on Render runs `CUTIEE_ENV=production`, which means:

- The CU loop uses Gemini (not the mock).
- The local Qwen path is gated off (`shouldUseLocalLlmForUrl` returns False).
- The optional `local_llm` dep group is NOT installed (`uv sync` skips it by default).
- The build step replaces `agent/memory/local_llm.py` with the stub at
  `agent/memory/local_llm_stub.py` so the production reflector / decomposer imports
  resolve without pulling torch / transformers.
- The `.dockerignore` excludes the Qwen source files from the worker image entirely.
- `scripts/verify_render_isolation.sh` is the local pre-push check; run it before
  pushing changes to `pyproject.toml` or any local LLM file.

See `DEPLOY-RENDER.md` for the full deployment walkthrough and `SPEC.md` for the
runtime contract.
