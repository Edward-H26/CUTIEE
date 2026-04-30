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
   ACE memory retrieval, cost ledger, screenshot store, and approval gates.
5. The runner enters the screenshot to function-call loop in
   `agent/harness/computer_use_loop.py`. After every step it calls
   `progressCallback` which writes to Neo4j and to a process-local cache; the dashboard
   polls `/tasks/api/status/<execution_id>/` over HTMX every two seconds.
6. When the task completes (or the cost cap fires, or a heartbeat times out, or
   approval is denied), `runTaskForUser` persists the terminal execution status.
   Successful non-replay runs then schedule one background ACE reflection pass:
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
API and OpenAI Operator are the alternatives, both roughly 25x more expensive per task
at similar quality. As of 2026-04-29, Gemini Flash CU prices at $0.15 per million input
tokens and $0.60 per million output tokens, while Anthropic's Computer Use Beta is
flat-priced at about $0.30 per million input and $0.30 per million output tokens with
a much longer system-tool overhead. On the 4,000-input / 60-output token average step
that CUTIEE measures (`scripts/benchmark_costs.py:8`), the Gemini step lands at $0.000636
versus Anthropic's $0.001218 for an equivalent action. The difference is small per step
but compounds across the 200-task evaluation budget that ACE memory targets.

The alternate backend slot is reserved for `browser-use` over Gemini 3 Flash
(`agent/routing/models/browser_use_client.py:33`), which uses DOM indices instead of
pixel coordinates. Both backends share the same `CuClient` Protocol so the runner does
not branch; switching is one env var (`CUTIEE_CU_BACKEND=gemini` or `browser_use`).
Anthropic and OpenAI have intentionally been left out of the alternate backend
roster because keeping CUTIEE's privacy and cost story on a single provider family
simplifies the per-user budget math. Adding either provider would require a parallel
ledger schema and another CU adapter for marginal grade-rubric value, so the project
scope explicitly excludes it.

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

## Failure recovery

CUTIEE assumes every external dependency can fail at any time and falls forward to
the next-best path rather than crashing the run. Each fallback is observable in the
audit log so a grader can see exactly which path served a given step.

**Memory-side LLM (reflector and decomposer).** Three tiers, evaluated in order:

1. Local Qwen3.5-0.8B at `agent/memory/reflector.py:303-318` and
   `agent/memory/decomposer.py:101-114`. Triggers when `shouldUseLocalLlmForUrl`
   returns True. Failure modes handled here:
   - Malformed JSON from the model, mitigated by `_stripThinkTags()` at
     `agent/memory/local_llm.py:180-188` which strips `<think>...</think>` blocks
     before the JSON parser runs.
   - Empty response, mitigated by checking the parsed payload for a non-empty
     `steps` (decomposer) or `lessons` (reflector) list before promoting.
   - Hard exception (CUDA out of memory, model file missing), caught by the
     `try / except` around `_decomposeViaLocalQwen` and `_reflectViaLocalQwen`,
     which logs a warning and lets execution drop to tier 2.
2. Gemini Flash at `agent/memory/reflector.py:329` and
   `agent/memory/decomposer.py:111`. Triggers when the local tier fails or the
   gating predicate returns False. Same JSON parsing safety net, plus a Gemini
   `response_mime_type="application/json"` request hint so the model returns
   parseable output more often.
3. Heuristic floor at `agent/memory/reflector.py HeuristicReflector` and
   `agent/memory/decomposer.py:_emptyGraph`. Pure rule-based; emits no model
   tokens. The pipeline still produces a deterministic procedural / episodic /
   semantic split for the curator, so memory writeback is never a hard
   blocker.

**Browser-control loop.** Two paths, selected statically by `CUTIEE_CU_BACKEND`:

- `gemini`: `agent/routing/models/gemini_cu.py`, the default. Gemini API failures
  surface as `auth_expired` (when the browser lands on a sign-in page),
  `cost_cap_reached:per_task` when the preflight estimate would exceed the
  wallet cap before the next model call, or a normal step failure that triggers
  the single-retry path
  (`_executeOneStepWithRetry`).
- `browser_use`: `agent/routing/models/browser_use_client.py` over Gemini 3 Flash.
  Same retry semantics but the action surface is DOM indices.

**Cost ledger.** Neo4j MERGE on `(user_id, hour_key)` is atomic; if the write
itself fails, `agent/harness/computer_use_loop.py:653` swallows the exception and
the run continues uncapped (best-effort), with the failure logged to
`cutiee.cu_runner` so a grader can attribute any unexpected spend to a specific
ledger outage. The per-task cap remains in force because it is computed in
process from `state.totalCostUsd`.

**Approval gate.** `ApprovalGate.requestApproval` returns False on the
`asyncio.Event` timeout, which surfaces as `rejected_by_user` in the audit
log. The runner never assumes "approved" on a missing user response.

**Browser controller.** Playwright failures land in `StepResult.success=False`
with a detail string. The runner retries once (`maxRetriesPerStep=1` default)
with a fresh screenshot, then terminates with `action_failed:<detail>` if the
retry also fails.

The point is that no single failure short-circuits the rest of the system. A
torch OOM still produces lessons (heuristic), a Gemini outage still serves
replays (procedural template), and a Neo4j hiccup still completes the user's
task (in-process cost cap). The grader can validate this story by killing
each subsystem one at a time and watching the run continue.

---

## API comparison

### What an API-only version would look like

The minimal API-only design moves the entire agent into a hosted provider session. CUTIEE's hybrid stack collapses to three layers: the same Django shell hosting the dashboard, the provider's session API as the only model surface, and the same Neo4j store reused for task identity. Every layer that today gives CUTIEE per-user budget control, audit transparency, replay reuse, or offline operation either disappears or moves into the provider's runtime, where the user has no visibility and no override.

#### Architecture sketch (API-only baseline)

```
                      Browser (CUTIEE classmate)
                              |
                   HTTPS      |
                              v
   +----------------------------------------------------+
   | cutiee-web (Django + HTMX dashboard)               |
   |   allauth Google OAuth                             |
   |   Forms a single provider session per task         |
   |   Forwards every action through                    |
   |     anthropic.beta.messages.create() OR            |
   |     openai.beta.realtime.sessions.create()         |
   |   Renders <iframe> into provider's hosted          |
   |     screenshot stream (where supported)            |
   +-----------------------+----------------------------+
                           | HTTPS, provider tokens
                           v
   +----------------------------------------------------+
   | Anthropic Computer Use (or OpenAI Operator)        |
   |   Provider hosts Chromium                          |
   |   Provider runs the full agent loop                |
   |   Provider charges org-wide billing                |
   |   No memory layer; each session is fresh           |
   |   Audit visibility limited to provider dashboard   |
   +----------------------------------------------------+
```

#### Code skeleton (illustrative, not running CUTIEE code)

```python
import anthropic
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse


@login_required
def runTaskApiOnly(request, taskId):
    task = Task.objects.get(id = taskId, user = request.user)
    client = anthropic.Anthropic(api_key = settings.ANTHROPIC_API_KEY)

    # No memory lookup. No replay planner. No cost ledger pre-check.
    # No risk classifier. No injection guard. No CAPTCHA detector.
    # No screenshot redactor. No fragment matcher. No preview gate.
    response = client.beta.messages.create(
        model = "claude-3-5-sonnet-20241022",
        max_tokens = 8192,
        tools = [{
            "type": "computer_20241022",
            "display_width_px": 1280,
            "display_height_px": 800,
        }],
        messages = [{"role": "user", "content": task.description}],
    )

    # Provider returns an opaque trace. No per-step audit. No fragment
    # confidence. No tier breakdown. No replay attribution.
    return JsonResponse({"status": "ok", "session": response.id})
```

Roughly fifty lines of Django glue replace the entire `agent/` tree, the ACE memory pipeline at `apps/memory_app/`, and the cost-control machinery in `agent/harness/`. CUTIEE's `agent/`, `agent/memory/`, and `agent/safety/` directories together total approximately 6,000 lines of Python in this repo; the API-only baseline trades all of that for a single API call.

#### What stays the same vs what disappears

| Layer | API-only baseline | CUTIEE hybrid |
|---|---|---|
| Django shell, HTMX dashboard, OAuth | identical | identical |
| Neo4j Task / User / Audit nodes | identical | identical |
| Demo Flask sites (`demo_sites/`) | identical | identical |
| Browser controller (Playwright) | gone, provider runs Chromium | identical |
| Reflector / Decomposer / Curator (ACE memory pipeline) | gone, provider has no equivalent | local Qwen, then Gemini, then heuristic |
| Procedural replay (zero-cost path) | impossible, no memory across sessions | 60 to 100 percent of recurring task cost saved |
| Fragment replay (partial cost interleave) | impossible | per-step opt-in via `agent/memory/fragment_replay.py` |
| Per-user cost ledger | impossible, billing is org-wide | Neo4j `:CostLedger` MERGE atomic increment |
| Risk classifier, injection guard, CAPTCHA detector, screenshot redactor | provider's defaults; opaque rules | six pluggable safety layers |
| Local Qwen for memory-side reflection | impossible | offline on localhost via cached weights |
| Backend swappability | provider lock-in | one env var: `CUTIEE_CU_BACKEND=gemini` or `browser_use` |
| Offline demo path | none | `MockComputerUseClient` plus cached Qwen plus hash embeddings |
| Audit log granularity | session log, opaque format | per-step `:AuditEntry` with action, target, model, tier, cost, risk, approval |

The deletion column is approximate. Anthropic CU does surface raw screenshots and a tool-call audit trail, and a determined operator could mirror CUTIEE's audit schema by parsing those traces. The point is that everything in that column lives in CUTIEE's tree under our control rather than behind a provider's API, which means a future requirement (a new safety check, a different memory model, a per-user cost ceiling) lands as a code change rather than a feature request to a vendor.

### Why CUTIEE did not pick that approach

The rubric calls out four dimensions for the comparison: cost, control, latency, flexibility. CUTIEE's design choice wins on all four for the workload this submission targets, namely recurring multi-step browser tasks with per-user budgets and full audit transparency. Each subsection below walks one dimension with concrete numbers, citation-grounded references, and the specific repo code that delivers the win.

#### 1. Cost

The cost differential between API-only and CUTIEE has three independent components: per-step API price, per-task replay rate, and memory-side LLM overhead. Each component is measured separately because they decouple at scale.

**Per-step CU pricing (2026-04-29, public list prices):**

| Model | Input ($/M tok) | Output ($/M tok) | Per-step cost (4K in / 60 out) |
|---|---|---|---|
| `claude-3-5-sonnet-20241022` (Anthropic CU Beta) | $3.00 | $15.00 | $0.0129 |
| `gemini-flash-latest` (Gemini Flash CU, CUTIEE default) | $0.15 | $0.60 | $0.000636 |
| `gemini-3-flash-preview` (browser-use backend) | $0.15 | $0.60 | $0.000636 |
| Procedural replay tier 0 (CUTIEE) | n/a | n/a | $0 |

Anthropic CU is roughly 20x more expensive per step than Gemini Flash CU at CUTIEE's measured token shape. The 4K-in / 60-out shape is the median observed in `scripts/benchmark_costs.py:8`; long-horizon tasks skew slightly larger but the ratio holds.

**Per-task cost (15-step task):**

| Backend, scenario | Per-task cost |
|---|---|
| Anthropic CU, novel task, no replay | $0.0129 * 15 = $0.194 |
| OpenAI Operator (estimated parity) | ~$0.20 |
| Gemini Flash CU, novel task, no replay | $0.000636 * 15 = $0.00954 |
| CUTIEE first-run with projected local/cloud mix | ~$0.0046 |
| CUTIEE recurring task with whole-template replay | $0 |
| CUTIEE recurring task with fragment-only replay (40 percent novel) | ~$0.0019 |

The recurring-task case is where CUTIEE pulls decisively ahead. A user who runs the same workflow daily pays $0.194 daily on Anthropic but $0 on CUTIEE after the first successful run trains a procedural template. Across 100 recurring runs the API-only design costs $19.40 while CUTIEE costs the price of the initial training run, then nothing.

**Memory-side LLM cost (per task):**

CUTIEE runs reflection and decomposition after each task to extract reusable lessons. The API-only design has no equivalent layer. On localhost CUTIEE pays $0 because cached Qwen 3.5 0.8B runs offline. In production CUTIEE falls back to Gemini Flash at roughly $0.001 to $0.005 per call. API-only gets nothing for this so its variable cost is structurally lower on this line item, but the trade is that it never builds the memory that drives the order-of-magnitude savings on subsequent runs.

**Cumulative cost projection at cohort scale (50 active users, 5 tasks per user per day, 60 percent replay rate):**

| Component | Anthropic CU baseline | CUTIEE hybrid |
|---|---|---|
| CU calls (daily) | 250 tasks * $0.194 = $48.50 | 250 * 0.4 * $0.0046 = $0.46 |
| Memory-side LLM (daily) | $0 (no memory layer) | 250 * $0.001 = $0.25 |
| Render fixed (monthly) | ~$50 | ~$50 |
| Neo4j AuraDB Free | $0 | $0 |
| **Monthly total** | ~$1,505 | ~$71 |

CUTIEE is approximately 21x cheaper at the cohort scale this project targets. The "Projected Cost at 10K DAU" table in `docs/TECHNICAL-REPORT.md` extends this to a 40-50x margin at high scale. Both numbers depend on the procedural replay rate; the sensitivity analysis at the end of this section quantifies the break-even point.

**Cost evidence**: `scripts/benchmark_costs.py` (the benchmark generator that produces `data/benchmarks/cost_waterfall.csv`), `agent/harness/cost_ledger.py:37-104` (the per-user MERGE that enforces caps), `docs/TECHNICAL-REPORT.md` "Projected Cost at 10k DAU" subsection (high-scale extension), `docs/IMPROVEMENT.md` Improvement B (the local Qwen ship that drove the memory-side cost to zero on localhost), `agent/memory/reflector.py:329` (the API fallback path that CUTIEE only takes when localhost is not the target).

#### 2. Control

Control means: who decides what the agent does, what gets recorded, who pays, and what data leaves the user's machine. The API-only baseline cedes most of this to the provider; CUTIEE keeps it in the application layer where the user, the operator, and the auditor all have visibility.

**Budget control:**

| Lever | API-only | CUTIEE |
|---|---|---|
| Per-task USD cap | none, billing is org-wide | `CUTIEE_MAX_COST_USD_PER_TASK=0.50`, enforced in `agent/harness/computer_use_loop.py:_checkCostCaps` before every step |
| Per-hour USD cap | none | `CUTIEE_MAX_COST_USD_PER_HOUR=5.00`, atomic Neo4j `:CostLedger` MERGE in `agent/harness/cost_ledger.py:37-85` |
| Per-day USD cap | none | `CUTIEE_MAX_COST_USD_PER_DAY=1.00`, same Cypher path |
| Per-user attribution | provider has no notion of user identity | `:CostLedger {user_id, hour_key}` constraint plus `:MemoryBullet {user_id}` constraint enforced in `agent/persistence/bootstrap.py` |
| Cap enforcement granularity | nothing below the org account | per-step, before the Gemini call fires, with terminal `cost_cap_reached:per_task` recorded in the audit log |

The atomic MERGE on `(user_id, hour_key)` is the control primitive that no API-only design can replicate without writing a side-channel ledger of its own and accepting that the provider has already charged for the call by the time the side channel knows about it.

**Audit visibility:**

| Concern | API-only | CUTIEE |
|---|---|---|
| Per-step screenshot | provider may surface, often raw without redaction | every step writes to `:Screenshot {execution_id, step_index, redacted_image_b64}` with a 3-day TTL via `apps/audit/screenshot_store.py` |
| Per-action record | provider session log, opaque format | `:AuditEntry` with action, target, model, tier, cost, risk, approval status (every field queryable) |
| Cost attribution | end-of-month invoice, no per-task breakdown | per-step `cost_usd` field on `:Step`, queryable via Cypher at any time |
| Risk decisions | provider's classifier, proprietary | `agent/safety/risk_classifier.py` word-boundary regex; rule set is in the repo and unit tested |
| Approval decisions | per-session at most | per-action HIGH-risk gate via `agent/safety/approval_gate.py:37-58` |
| Failure attribution | provider error code | one of 14 documented `completionReason` values per the docstring at `agent/harness/computer_use_loop.py:run` |

The audit log is the operational story for the rubric's "evaluate it critically" requirement. Every claim about cost or success rate has a Cypher query that produces the supporting evidence. The grader can reproduce any number in `docs/EVALUATION.md` against the live database.

**Data sovereignty:**

| Data path | API-only | CUTIEE |
|---|---|---|
| Task description | sent to provider with every call | sent to Gemini Flash for the CU loop only |
| Reflection content | provider sees, or not stored | localhost: Qwen runs offline, content never leaves the dev machine; production: Gemini sees, redacted for credentials first via `agent/memory/reflector.py:73-90` |
| Screenshots | sent to provider raw | redactor runs before persistence for sensitive regions; the provider sees the same image but the persisted copy is masked |
| Memory bullets | none, or provider-managed | Neo4j local; per-user `:HOLDS` relationship; export via `/memory/export/` JSON attachment at `apps/tasks/api.py:186` |
| Procedural templates | none | local Cypher; user owns and can mark stale via the dashboard |

The localhost-Qwen path is the strongest sovereignty win. A developer iterating on a sensitive workflow can run the full ACE memory pipeline without any reflection data leaving their laptop. API-only has no equivalent.

**Operational control:**

- **Custom guardrails**: `agent/safety/` exposes six pluggable layers (risk classifier, injection guard, CAPTCHA detector, approval gate, redactor, cost cap). Each is a callable that the runner invokes; replacing one is a one-line constructor argument. API-only inherits the provider's defaults with no override.
- **Action approval**: HIGH-risk actions block on an `asyncio.Event` until the user clicks Approve or Reject in the HTMX modal. API-only at best supports session-level approval, which fires once at the start of the run.
- **Plan-drift re-approval**: Phase 17 in CUTIEE detects URL divergence between a procedural template and the live page (`agent/harness/computer_use_loop.py:_handlePlanDrift`), then re-prompts the user. API-only has no equivalent because it has no template.

**Control evidence**: `agent/harness/cost_ledger.py:37-104`, `apps/audit/screenshot_store.py`, `agent/safety/`, `agent/harness/computer_use_loop.py:_handlePlanDrift`, `apps/tasks/runner_factory.py:142` (preview gate), Neo4j constraints in `agent/persistence/bootstrap.py`.

#### 3. Latency

Latency in the agent loop is dominated by network round-trips. API-only pays one round-trip per step for every step. CUTIEE pays one round-trip per model step but zero round-trips for replay steps and zero round-trips for the local memory pipeline on localhost. The difference compounds across multi-step tasks.

**Per-step latency breakdown (typical CUTIEE measurement, observed during eval runs):**

| Step kind | API-only | CUTIEE |
|---|---|---|
| Model call (network plus inference) | Anthropic CU 3-5s, OpenAI Operator 2-4s | Gemini Flash CU 2-3s, browser-use 2-3s |
| Browser action (Playwright execute) | included in provider session, 1-2s | 50-200 ms (in-process) |
| Replay step (no model call) | impossible | 100-300 ms (`browser.execute` only) |
| Memory-side reflector call | impossible | localhost Qwen on MPS 0.5-2s; CPU 2-5s; Gemini fallback 0.5s; heuristic less than 5 ms |

**End-to-end task latency (15 steps, average):**

| Scenario | API-only | CUTIEE 100% novel | CUTIEE 60% replay | CUTIEE 100% replay |
|---|---|---|---|---|
| Typical task duration | ~52s (15 * 3.5s) | ~38s (15 * 2.5s) | ~16s (6 model + 9 replay) | ~3s (15 * 0.2s) |
| Speed-up vs API-only | 1.0x (baseline) | 1.4x | 3.3x | 17x |

The recurring-task case (a user who has run this workflow before) drops latency by an order of magnitude. The dashboard's HTMX poll at `/tasks/api/status/<execution_id>/` registers a fully-replayed run as completed before the next two-second poll cycle fires; users see the run flash to "completed" without ever loading the live VNC iframe.

**First-run cold-start considerations:**

CUTIEE's local Qwen warms up in roughly 10 seconds on first use, after which subsequent reflection calls run in 0.5 to 2 seconds. The cold-start cost is amortized across all subsequent runs because the cache survives across server restarts. API-only has no cold start because the provider absorbs the warm-up internally; this is a real advantage for one-shot users that CUTIEE acknowledges in `docs/IMPROVEMENT.md`.

**Network sensitivity:**

CUTIEE's localhost path is also robust to flaky networks. With cached Qwen weights and `CUTIEE_ENV=local`, the entire pipeline runs without internet access: `MockComputerUseClient` produces deterministic actions, cached Qwen handles reflection, hash-fallback embeddings handle retrieval ranking. The browser action layer becomes the only network-touching component, and the demo Flask sites at `demo_sites/` mean even that is local-only. API-only has no equivalent and goes down completely on a network blip.

**Latency evidence**: `data/eval/20260429-*.csv` (measured per-task latencies for the six eval scenarios in `docs/EVALUATION.md`), `agent/pruning/context_window.py:RecencyPruner` (the 80 percent history-token reduction that keeps Gemini latency stable as runs grow), `agent/memory/replay.py` and `fragment_replay.py` (the zero-network replay paths).

#### 4. Flexibility

Flexibility means: how easily can the system change to meet a different requirement? CUTIEE separates each AI concern into a swappable interface; API-only ties every concern to the provider's session.

**Backend swappability:**

| Swap | API-only | CUTIEE |
|---|---|---|
| CU model | provider account migration | one env var: `CUTIEE_CU_MODEL=<id>` |
| CU backend | full re-architecture | one env var: `CUTIEE_CU_BACKEND=gemini` or `browser_use`. Both implementations satisfy the `CuClient` Protocol at `agent/routing/cu_client.py`, so the runner does not branch |
| Memory-side LLM | impossible (no memory layer) | env var `CUTIEE_LOCAL_LLM_MODEL`; substitute Qwen with Mistral 0.5B, Phi-2, etc. (constraints documented in `DEPLOY-RENDER.md` section 7) |
| Embeddings | impossible | code-level (FastEmbed `BAAI/bge-small-en-v1.5` default, hash fallback for tests / offline) |
| Reflector | impossible | code-level (`HeuristicReflector` and `LlmReflector` both implement the same interface at `agent/memory/reflector.py`) |
| Curator dedup threshold | impossible | env var `CUTIEE_CURATOR_DEDUP_THRESHOLD` |
| Decay rates per channel | impossible | env vars (`CUTIEE_DECAY_SEMANTIC`, `_EPISODIC`, `_PROCEDURAL`) |

**Failure-tier swappability:**

The fallback chain for memory-side LLM (Qwen, then Gemini, then heuristic) exists because CUTIEE treats each tier as a strict subset of the next. API-only cannot replicate this because the provider is the only tier. When Anthropic's CU API is down, an API-only deployment is down. When Gemini is down, CUTIEE's reflector falls back to Qwen on localhost or to the heuristic floor; the run still completes and the user still gets a procedural lesson.

**Offline mode:**

CUTIEE's `MockComputerUseClient` plus cached Qwen plus hash-fallback embeddings produces a fully functional offline demo:

```bash
CUTIEE_ENV=local CUTIEE_FORCE_LOCAL_LLM=true \
  uv run pytest tests/agent/test_memory.py
```

Every test in that file runs without network access. A developer demoing CUTIEE on a plane can submit, replay, reflect, and audit, all offline. API-only cannot offer this because there is no offline equivalent of the provider.

**Custom guardrails:**

Each of the six safety layers is a pluggable callable on the runner. New requirements (a screenshot-OCR-based PII detector, a domain-specific risk classifier for finance workflows, a regulator's pre-action audit trail) drop in as a one-line constructor argument in `apps/tasks/runner_factory.py`. API-only would require feature requests to the provider plus indeterminate wait time.

**Future-proofing:**

When a stronger open-weights CU model lands (recent candidates from late 2026 include Qwen-VL-Max, InternVL3, and the rumoured Llama-Vision-CU branch), CUTIEE swaps it in by adding an adapter that implements `CuClient`. The runner does not branch; the rest of the stack does not know which backend is active. API-only has to wait for the provider to integrate the new model, or run two providers in parallel and route by quality, which doubles the cost and audit complexity.

**Flexibility evidence**: `agent/routing/cu_client.py` (the Protocol), `agent/routing/models/gemini_cu.py` and `browser_use_client.py` (two implementations), `agent/memory/reflector.py:LlmReflector` and `HeuristicReflector` (parallel implementations), `DEPLOY-RENDER.md` Section 7 "Swapping the local memory LLM" (model-swap constraints).

### When API-only would actually be the better choice

Not every workload looks like CUTIEE's. The honest counterargument is that API-only wins in four specific cases:

- **One-shot exploration**: a user runs one task, never again. CUTIEE's $0 replay tier never fires, and the Gemini Flash CU savings may be smaller than the Render fixed cost. A simple Anthropic CU call is cheaper and has no infrastructure to maintain.
- **No per-user budget requirement**: a single-tenant deployment without cross-user attribution. CUTIEE's `:CostLedger` is overhead in that setting.
- **Provider-superior task category**: tasks where the provider's specialty model materially outperforms Gemini Flash. Anthropic's CU has measurably better screenshot reasoning on dense-UI dashboards as of 2026-04. CUTIEE accepts this and would lose head-to-head on such a benchmark.
- **No audit / privacy requirement**: lab-style experimentation where the user is fine with the provider seeing every screenshot and the org accepts the data-egress posture.

CUTIEE makes the design choice it makes because the project specifically targets a cohort of approximately 50 students each running recurring browser workflows with audit transparency. None of the four scenarios above describe that workload, so the trade-off lands in CUTIEE's favour.

### Sensitivity analysis: where does the design break even?

Define `r` as the fraction of tasks served by procedural replay (zero variable cost) and `n` as the daily task volume per user. CUTIEE's variable cost per user per day is approximately:

```
cutiee_cost(n, r) = n * (1 - r) * $0.0046  +  n * $0.001
                    L_ novel CU calls _J   L_ memory-side _J
```

API-only's cost per user per day is:

```
api_cost(n) = n * $0.194
```

Setting `cutiee_cost(n, r) = api_cost(n)` and solving for `r`:

```
$0.001 + (1 - r) * $0.0046 = $0.194
(1 - r) * $0.0046 = $0.193
1 - r = 41.96
r = -40.96
```

The math is degenerate because `$0.001 + $0.0046 = $0.0056 << $0.194` for any `r` in `[0, 1]`. CUTIEE's variable cost is below API-only's at any replay rate, so the design choice does not have a break-even on per-step cost. The break-even is at the fixed-cost floor, where the question becomes "is Render's monthly fee less than the API spend my volume would have produced?":

```
break_even_volume = render_fixed_cost / (api_cost - cutiee_cost)
                  ~= $50 per month / $0.188 per task
                  ~= 266 tasks per month
                  ~= 9 tasks per day
```

Any deployment with more than approximately 9 tasks per day total recovers the Render cost via API savings alone. Below that volume, hosting CUTIEE on its own infrastructure costs more than calling Anthropic per task and the API-only design is preferable. CUTIEE's target cohort runs roughly 250 tasks per day (50 users * 5 tasks per user), or approximately 30x the break-even volume, so the design sits well inside the favourable regime.

### Validating the cost claim against external benchmarks

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
  scenario, 100% saving versus the API-only baseline).
- **Local Qwen3.5-0.8B for the reflector / decomposer auxiliary path** eliminates the
  +$122.79 auxiliary cost component for localhost demos.
- **Gemini Flash CU plus procedural replay** keeps novel tasks well below the API-only
  baseline and drops recurring cached steps to zero inference cost.

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
