# CUTIEE — AI Workflow

This document covers the AI integration for INFO490 Part 3: where AI
enters the system, how user input is processed, which models run, how
outputs return to the user, and why the design beats a pure-API baseline.

## AI workflow at a glance

```
user task (text)
   │
   ▼
apps.tasks.services.runTaskForUser
   │
   ├── ACEMemory.retrieveRelevantBullets(task)            # semantic retrieval
   │      └── if procedural cluster matches above 0.85
   │             → ReplayPlanner.findReplayPlan(task)
   │             → orchestrator replays, zero inference
   │
   └── orchestrator.runTask
         │
         loop:
         ├── browser.observe()                            # DOM extraction
         ├── pruner.prune(state.history)                  # context compression
         ├── memory.retrieveRelevantBullets(task)         # prior knowledge block
         ├── router.routeAndPredict(task, dom, ctx)       # tier selection + escalation
         │      └── classifyDifficulty → pick T1/T2/T3
         │      └── confidence probe → escalate if needed
         ├── classifyRisk(action)                         # safety gate
         ├── approvalGate.requestApproval (if HIGH)
         ├── browser.execute(action)
         ├── auditSink(payload)                           # immutable audit
         └── progress_backend.publish (HTMX live)
   │
   ▼
ACEPipeline.processExecution(state)
   ├── Reflector.reflect(state) → LessonCandidates
   ├── QualityGate.apply(...) → accepted / rejected with diagnostics
   ├── Curator.curate(accepted) → DeltaUpdate
   └── memory.applyDelta + memory.refine
```

Every numbered surface is a Python module under `agent/`. The AI feature
is the entire loop; nothing about the application is "an API call wrapped
in Django."

## Models in use

CUTIEE supports two model stacks; the active stack is decided by
`CUTIEE_ENV`.

### Local stack (`CUTIEE_ENV=local`)

A single Qwen3.5 0.8B Q4_K_M GGUF backs all three router tiers. The
prompt envelope changes per tier:

- Tier 1 (`simple`): task + 600 chars of DOM. ~250 input tokens.
- Tier 2 (`general`): task + 2,400 chars of DOM + 1,200 chars of pruned
  history. ~1,200 input tokens.
- Tier 3 (`full_context`): task + full DOM + full pruned history. ~5,000
  input tokens.

`llama-server --logprobs 5` exposes top-token probabilities so the
confidence probe can read mean-logprob and exponentiate. Inference cost
is treated as zero.

### Production stack (`CUTIEE_ENV=production`)

Three Gemini 3.1 variants:

CUTIEE defaults to **Computer Use (screenshot + pixel coordinates) for every task**
as of 2026-04. Google extended the `ComputerUse` tool to the regular Flash family,
so CU now runs at flash pricing.

### Default — Computer Use

| Model | Approx $/MT input | Approx $/MT output | Notes |
|-------|-------------------|--------------------|-------|
| **gemini-flash-latest** | **0.15** | **0.60** | Default. Auto-tracks Google's latest Flash. |
| gemini-3-flash-preview | 0.15 | 0.60 | Pinned alternative. |
| gemini-2.5-computer-use-preview-10-2025 | 1.25 | 5.00 | Specialty preview, ~8× more expensive. Opt-in only. |

Override via `CUTIEE_CU_MODEL=<model-id>` in `.env`.

### Opt-in DOM router (`?use_cu=0`)

Faster on simple HTML forms but blind to canvas / iframes / custom JS widgets.
Pro variants are explicitly disabled at the client level (`GeminiCloudClient.__post_init__`
raises on any `*-pro*` id) to keep escalation cost bounded.

| Tier | Model | Approx $/MT input | Approx $/MT output |
|------|-------|-------------------|-------------------|
| 1 | gemini-3.1-flash-lite-preview | 0.075 | 0.30 |
| 2 | gemini-3-flash-preview | 0.15 | 0.60 |
| 3 | gemini-3-flash-preview | 0.15 | 0.60 |

Pricing constants live in `agent/routing/models/gemini_cloud.py`. Every
call records `usage_metadata.prompt_token_count` and
`usage_metadata.candidates_token_count` so the audit log captures actual
spend, not estimates.

## How user input is processed

1. The user submits a task via `TaskSubmissionForm` (`apps/tasks/forms.py`).
   The form takes a description, an optional starting URL, and an
   optional domain hint.
2. The view calls `apps.tasks.repo.createTask` which writes a `:Task`
   node into Neo4j scoped to the `:User` node.
3. Clicking "Run task now" hits `POST /tasks/<id>/run/`, which spawns a
   background thread that calls `runTaskForUser`.
4. `runTaskForUser` builds the right orchestrator for the active
   environment and runs the task. Every step publishes a JSON snapshot to
   the progress backend (in-memory locally, Redis in production).
5. The detail page polls `GET /tasks/api/status/<execution_id>/` every
   two seconds via HTMX and renders the latest snapshot.

## Output generation

The router returns an `Action` dataclass for every step:

```python
Action(
    type=ActionType.CLICK,             # one of click/fill/navigate/select/...
    target="#submit",                   # CSS selector or URL
    value=None,
    reasoning="click the primary CTA",
    model_used="gemini-3-flash-preview",
    tier=2,
    confidence=0.91,
    risk=RiskLevel.LOW,
    cost_usd=0.00041,
)
```

The browser controller executes the action. The result, plus DOM hash,
duration, and verification status, becomes an `ObservationStep` that is
appended to `AgentState.history` and persisted as a `:Step` node linked
to the run's `:Execution`.

## Guardrails

- **Risk classification.** `agent/safety/risk_classifier.py` runs a
  keyword sweep over the action target, value, reasoning, and surrounding
  task description. High-risk actions (delete, payment, send email,
  cancel subscription, etc.) require explicit approval through
  `agent/safety/approval_gate.py`. Rejected approval halts the run with
  `completionReason="rejected_by_user"`.
- **Confidence probe.** Every model call's confidence is checked against
  the per-tier threshold. Low confidence escalates to the next tier;
  Tier 3 is the terminal call.
- **Quality gate.** `agent/memory/quality_gate.py` rejects low-quality
  reflections so noisy traces never pollute the bullet store. The
  diagnostics surface the rejection reason.
- **Credential isolation.** `:MemoryBullet` nodes with `is_credential=True`
  are encrypted at rest with `cryptography.fernet` and never appear in
  any prompt block. They surface only via the explicit
  `getCredential(domain)` accessor used by the replay variable resolver.
- **Verification per step.** Each browser step records `verificationOk`.
  Failed steps trigger the self-healing path (re-grounding through a
  higher tier) instead of silently continuing.

## API comparison

### What a pure API solution would look like

A purely API-based solution would forward the task description and the
current screenshot to a single frontier vision model on every step. Each
step would round-trip the entire DOM, with no procedural memory and no
tier routing. A 15-step task would burn ~$0.30 and the same task next
week would burn $0.30 again.

### Why CUTIEE doesn't choose that

| Concern | API-only | CUTIEE |
|---------|----------|--------|
| Cost on the first run | $0.30 | $0.021 |
| Cost on the second run | $0.30 | $0.000 |
| Cost asymptote at 95% replay | $0.30 | $0.003 |
| Latency on replay | 30-60 s | 1-2 s |
| Privacy: DOM leaves the device | yes, every step | no, replay runs locally |
| Vendor lock-in | total | none, model-pluggable |
| Local development | impossible without keys | offline via Qwen |
| Failure path | retry the same call | escalate tier or replay-with-self-heal |

The compound savings come from three independent mechanisms:

1. **Procedural replay** removes inference entirely for recurring tasks.
   This is the dominant savings (replay covers 80% of typical user
   workflows after a few weeks of usage).
2. **Temporal pruning** reduces per-call input tokens by 60-80% on long
   workflows. Important even on novel tasks because cost scales with
   context length.
3. **Multi-tier routing** sends easy decisions to the cheapest viable
   model. Tier 1 (flash-lite) is roughly 17x cheaper per token than
   Tier 3 (pro); when 70-90% of decisions route to Tier 1, the average
   cost per inference falls toward Tier 1 even on novel tasks.

### When CUTIEE would lose to API-only

If every task were one-shot and the underlying interface mutated weekly
(no replay benefit), and every step were borderline-hard (constant Tier 3
escalation), CUTIEE would carry pruning savings but not replay savings.
The breakeven sits around 1.5 runs per task; below that, the engineering
overhead doesn't pay for itself. CUTIEE is built for the recurring-task
profile that defines real user behaviour.

## Design decisions worth justifying

### Why Qwen3.5 0.8B for local

The smallest model that produces structured JSON reliably. Smaller
checkpoints (Qwen 0.5B, ShowUI 2B, etc.) routinely fail to obey the
JSON-only output format under temperature 0.2. The 0.8B checkpoint runs
on a CPU laptop with ~2 GB of RAM, no GPU required, which makes the
"developer can iterate offline" promise real.

### Why Gemini 3.1 for production

Three reasons. First, Gemini's three-tier pricing maps cleanly to the
router's three-tier shape, so the same routing code works without
abstraction layers. Second, Gemini natively returns
`response.usage_metadata` so per-call cost is exact, not estimated.
Third, Gemini 3.1 supports JSON mime type natively, which removes the
"please reply only with JSON" prompt-engineering tax.

### Why Neo4j for everything

Procedural memory is fundamentally a graph: templates point to ordered
steps, steps point to verifications and model calls, templates evolve via
`SUPERSEDED_BY` edges. A single graph database lets CUTIEE serve
authentication, sessions, domain entities, and memory from one
connection pool. The runtime never touches a relational table for
application data.

### Why HTMX over a SPA

The agent's progress is the only piece of the UI that needs to update
live. HTMX polling against a server-rendered partial is roughly fifty
lines of code; a React/Vue stack would be hundreds. The team-of-one
constraint motivates the choice.

### Why `StubBrowserController`

Render's web tier doesn't have Playwright binaries by default. The stub
browser lets `runTaskForUser` complete end-to-end so the UI surface,
audit log, and memory pipeline all work in production even before a
worker dyno with browser binaries is provisioned. Real browser sessions
move to a Celery/RQ worker once the user opts in.

### Why hash-based embeddings as default

FastEmbed loads ~200 MB of weights at first use and adds 30+ seconds of
warm-up. The hash-based fallback (`agent/memory/embeddings.hashEmbedding`)
keeps the cosine-similarity surface deterministic so the entire pipeline
boots and tests in milliseconds. Operators flip
`useHashEmbedding=False` when they want real semantic embeddings.

## Where the AI is in the user flow

| Click path | Code path |
|------------|-----------|
| `/tasks/` → "Submit task" | `apps/tasks/forms.py` → `apps/tasks/views.py:create_task` → `apps/tasks/repo.py:createTask` |
| `/tasks/<id>/` → "Run task now" | `apps/tasks/api.py:run_task_view` → `apps/tasks/services.py:runTaskForUser` → `agent/harness/orchestrator.py:Orchestrator.runTask` |
| HTMX progress | `apps/tasks/api.py:task_status` → `apps/tasks/progress_backend.py:fetchProgress` |
| `/memory/` | `apps/memory_app/views.py:bullet_list` → `apps/memory_app/repo.py:listBulletsForUser` |
| `/memory/export/` | `apps/tasks/api.py:memory_export` |
| `/audit/` | `apps/audit/views.py:audit_list` → `apps/audit/repo.py:listAuditForUser` |
| `/tasks/dashboard/` | `apps/tasks/views.py:cost_dashboard` + Chart.js fetching `/tasks/api/cost-timeseries/` and `/tasks/api/tier-distribution/` |

The AI feature is not a sidecar. It is the application.
