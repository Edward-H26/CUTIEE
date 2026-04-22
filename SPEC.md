# CUTIEE Specification

**Computer Use agentIc-framework with Token-efficient harnEss Engineering**

This document specifies the final runtime behavior of CUTIEE after the 17-phase integration of browser-use with fragment-level replay, a pre-run preview, and safety guardrails. It reflects design decisions captured during the 2026-04-21 interview cycle and is the source of truth for the wired-up system.

## 1. Scope and Audience

CUTIEE is a browser-driving Computer Use agent targeted at the INFO490 course cohort (roughly a few dozen classmates plus the instructor). It is not a public product. The single deployment lives on paid Render plus Neo4j AuraDB Free. Each classmate authenticates with their university Google account and runs one task at a time against any URL they like. Live execution is visible as a VNC stream rendered in the dashboard's main panel next to the task submission surface.

## 2. Architectural Invariants

Seven invariants hold for every code path in every deployment.

1. **One runner**: every task flows through `ComputerUseRunner` at `agent/harness/computer_use_loop.py`. No framework-supplied loop replaces it.
2. **Pluggable CU client**: the client is a `CuClient` Protocol implementation. Today there are two: `GeminiComputerUseClient` (default, `gemini-flash-latest`) and `BrowserUseClient` (browser-use wrapping `gemini-3-flash-preview`). Selection happens at boot via `CUTIEE_CU_BACKEND`; classmates cannot switch per task.
3. **Single credential**: `GEMINI_API_KEY` is the only model credential in either backend. The key lives plaintext in the deployment's `.env`. Classmates either use the shared deployment (the instructor's key) or self-host a clone with their own key. Neo4j never stores the key.
4. **Single database**: Neo4j is the only durable store. Cost ledgers, approval queues, preview approvals, audit entries, screenshots, and memory bullets all land on Neo4j nodes. No Redis, no SQLite, no external queue.
5. **Canonical action types**: every adapter emits `ActionType` enum values from `agent/harness/state.py`. The replay planner and fragment matcher regex-parse the enum value out of procedural bullets, so non-canonical names break replay silently. A merge gate enforces a replay round-trip test.
6. **No silent fallback**: unknown env-var values raise `RuntimeError` at config parse. Missing dependencies raise at construction, not at first use.
7. **One task per user**: the task queue rejects or blocks a second submission while a first is running. One VNC session per active user; the worker does not multiplex.

## 3. Deployment Topology

One canonical deployment. Two Render services, one Neo4j AuraDB, and the classmate's browser.

```
                         Classmate's browser
                             │        │
                             │        │  noVNC WebSocket
                      HTTPS  │        │  (iframe, public URL)
                      HTMX   │        │
                             ▼        ▼
  ┌────────────────────────────────┐  ┌─────────────────────────────┐
  │ cutiee-web   (Render Python)   │  │ cutiee-worker (Render       │
  │                                │  │                Docker)      │
  │   Django + HTMX                │  │   Xvfb :99                  │
  │   allauth Google OAuth         │  │   fluxbox                   │
  │   ComputerUseRunner            │──┼─►Chromium (headed)          │
  │   BrowserController (Playwright│  │CDP  --remote-debugging=9222 │
  │                  connect_over_ │  │9222                         │
  │                  cdp)          │  │   x11vnc :5901              │
  │   CuClient (Gemini CU or       │  │   websockify :6080          │
  │             browser-use)       │  │        → /usr/share/novnc   │
  │                                │  │                             │
  │   Renders <iframe src=         │  │   (No Python runtime.       │
  │     $CUTIEE_NOVNC_URL>         │  │    Writes nothing to Neo4j.)│
  └────────────┬───────────────────┘  └─────────────────────────────┘
               │
               │  Cypher over bolt+s://
               ▼
       Neo4j AuraDB   (single durable store)
         :User, :Task, :Execution, :Step,
         :MemoryBullet, :AuditEntry, :Screenshot,
         :CostLedger, :ActionApproval, :PreviewApproval,
         :ProgressSnapshot, :UserPrompt
```

`cutiee-web` is the only Python process. It runs the CU loop, the safety gate, the Cypher writes, and the template that embeds the iframe. `cutiee-worker` is a headed-browser container: Xvfb provides the display, Chromium runs inside it with CDP bound to `0.0.0.0:9222`, and websockify streams the framebuffer to any browser that connects to the public noVNC URL on port 6080. CDP reaches `cutiee-worker` from `cutiee-web` over Render's private network, never over the public internet.

Each active task owns one Xvfb + Chromium + VNC trio. The dashboard's main content area embeds a noVNC iframe pointed at the worker's websockify port. Classmates see the live framebuffer in real time and can click inside it as a manual fallback if the agent stalls.

## 4. Authentication and Credentials

**User auth**: Google OAuth via `django-allauth[socialaccount]>=65.0`. The only required environment variables at boot are `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. No magic-link fallback, no username/password.

**Model credential**: `GEMINI_API_KEY` is read from the deployment's `.env`. It is never written to Neo4j, never rendered in logs, and never returned in API responses. Classmates who want their own budget clone CUTIEE locally and set their own `.env`. The shared Render deployment carries the instructor's key by default.

**Risk acknowledged**: a shared key means per-user cost caps are load-bearing. Phase 4 wallet caps plus Phase 7 heartbeat plus single-concurrency together bound the worst-case spend per classmate per day.

## 5. CU Backend Contract

Two backends. Both satisfy the `CuClient` Protocol at `agent/routing/cu_client.py`.

| Backend | Env value | Wrapped LLM | Pricing per M tokens |
|---------|-----------|-------------|----------------------|
| Gemini CU (default) | `gemini` | `gemini-flash-latest` | $0.15 input / $0.60 output |
| browser-use | `browser_use` | `gemini-3-flash-preview` | $0.15 input / $0.60 output |

Both backends return `ComputerUseStep` instances that carry a canonical `Action`. Native metadata rides inside `Action.reasoning` behind a `__adapter_meta__{...}__` JSON marker so the audit schema stays frozen. The browser-use adapter's DOM-indexed actions (`click_element_by_index`, `input_text`, `scroll_down`, `scroll_up`, `go_to_url`, `send_keys`, `done`) translate one-to-one into `ActionType` values; the adapter computes a bbox center for every click so coordinates survive replay.

## 6. Runtime Flow

The flow below is the wired-up version in `ComputerUseRunner.run()`. Every collaborator is optional; the runner keeps its pre-phase behavior when a field is `None`.

```
User submits task
  │
  ▼
apps.tasks.services.runTaskForUser
  │   creates :Task, dispatches background thread
  ▼
ComputerUseRunner.run(userId, taskId, taskDescription, executionId)
  │
  ├ _resolveFragmentPlan  ──► FragmentPlan (may be empty)
  │
  ├ _runPreviewAndAwaitApproval
  │     writes :PreviewApproval {status:"pending"} with the generated
  │     summary. HTMX dashboard polls and renders Approve/Cancel.
  │     If user cancels, state.markComplete("user_cancelled_preview")
  │     and return immediately without touching the browser.
  │
  ├ browser.start  ──► Xvfb Chromium; VNC already streaming
  │
  ├ if whole-template replayPlan found:  _executeReplay  (zero cost)
  │
  ├ elif prematchedNodes set:  _executePrematchedNodes  (zero-cost prefix)
  │
  ├ elif initialUrl:  _recordInitialNavigation
  │
  ├ _runLoop(state, fragmentPlan)
  │     For each stepIndex in [current, maxSteps):
  │       ▸ if fragment matches AND not requires_model_value:
  │           _executeFragment  (zero cost, approval on HIGH)
  │       ▸ else:
  │           _executeOneStepWithRetry
  │             1. captcha_detector  ──► if hit, mark_complete
  │             2. injection_guard   ──► annotate risk on hit
  │             3. client.nextAction (Gemini or browser-use)
  │             4. classifyRisk
  │             5. cost_ledger       ──► if over cap, mark_complete
  │             6. heartbeat.check   ──► if terminate, mark_complete
  │             7. approvalGate      ──► HIGH risk blocks
  │             8. browser.execute
  │             9. capture screenshot + redactor
  │            10. screenshotSink (Neo4j 3-day TTL)
  │            11. auditSink (:AuditEntry)
  │
  ├ browser.stop  ──► tears down Xvfb + Chromium + VNC
  │
  └ ACEPipeline.processExecution  (ONLY if not state.replayed)
        Reflector  ──► QualityGate ≥0.60  ──► Curator  ──► applyDelta
        refine()  enforces maxBullets + per-type quota (60 / 25 / 15)
```

### Plan-Drift Handling (Phase 17, new)

When the fragment matcher produced a plan at preview time but a mid-run step's observed page state diverges from the fragment's recorded `expected_url` or `expected_phash`, the runner pauses and creates a fresh `:PreviewApproval` node with a revised summary ("plan drifted at step N: ..."). The loop blocks on approval before continuing. On cancellation, the run ends with `completionReason="plan_drift_cancelled"`.

## 7. ACE Memory Model

Three memory types with independent decay channels. Retrieval ranks by `0.60 * relevance + 0.20 * normalizedStrength + 0.20 * typePriority` plus capped facet bonuses.

| Channel | Decay rate | Rationale |
|---------|------------|-----------|
| Semantic | 0.01 | Facts drift gradually |
| Episodic | 0.05 | Run-bound memories fade fast |
| Procedural | 0.01 | **Bumped from 0.002** in Phase 12 so bad workflows eventually disappear |

**Facet bonus cap**: 0.25 cumulative. Prevents a bullet tagged with every facet from overpowering its relevance score.

**Per-type quota on refine**: 60 percent procedural, 25 percent episodic, 15 percent semantic. `maxBullets=100` total.

**Decay-to-zero sweeper (new)**: a nightly job removes bullets whose `totalDecayedStrength <= 0.01`. This replaces any hard TTL; memory lifetime is entirely a function of how useful the bullet proves across retrievals.

**Per-user isolation**: strictly enforced. The Neo4j `bullet_user_scope` constraint (Phase 9) requires `user_id IS NOT NULL` on every `:MemoryBullet`. Bullets are never shared across classmates. There is no opt-in publish.

**Fragment-level replay (Phase 15)**: each procedural bullet is evaluated independently. Bullets whose stored `value` field was populated become value-variant fragments (coordinate replays; value re-derived by the model). Bullets with empty `value` replay verbatim at zero cost.

## 8. Safety Guardrails

Seven layers, each gated behind an env var so deployment can dial intensity.

| Phase | Guard | Env toggle | Failure mode |
|-------|-------|------------|--------------|
| 4 | Wallet cap (Neo4j `:CostLedger`) | `CUTIEE_MAX_COST_USD_PER_TASK`, `CUTIEE_MAX_COST_USD_PER_HOUR` | `cost_cap_reached` |
| 5 | Injection guard (URL strip + OCR) | `CUTIEE_ALLOW_URL_FRAGMENTS` | HIGH risk auto-escalation |
| 6 | CAPTCHA watchdog (fingerprint scan) | always on when module available | `captcha_detected` |
| 7 | Wall-clock heartbeat | `CUTIEE_HEARTBEAT_MINUTES` | `wallclock_heartbeat` |
| 8 | Screenshot redactor | always on via runner field | masks password / SSN / CVV regions |
| 9 | CDP tab fencing | always | fresh page on attach, never inherits user tabs |
| 16 | Pre-run preview | required in production | `user_cancelled_preview` |

**Approval density**: one preview approval per task, then autonomous. HIGH-risk individual actions still gate through the existing `ApprovalGate`; the gate persists to Neo4j as `:ActionApproval` so HTMX polling picks them up.

**VNC disconnect**: treated as loss of consent. The runner aborts the current step and marks the run complete with `completionReason="live_view_lost"`.

## 9. UI / UX Specification

Sidebar (six items, all persistent):

```
WORKSPACE
  Tasks       ← home; task submission + live VNC panel
  Cost dashboard
  Memory
  Audit log

SETTINGS
  Models      ← read-only view of CUTIEE_CU_BACKEND
  Approvals   ← active pending approvals only
```

**Main panel (Tasks view)**:

- **No active task**: empty white space with a single prominent "Submit a task" CTA.
- **Preview phase**: a card renders the CuClient-generated natural-language plan with Approve and Cancel buttons. Status polls every 1 second from the `:PreviewApproval` Neo4j node.
- **Running task**: noVNC iframe fills the panel. Live framebuffer updates at the VNC server's native rate. Progress events render as a thin strip below the iframe.
- **Plan drift**: the noVNC iframe remains visible; a modal overlay surfaces the revised plan text and new Approve / Cancel buttons.

**Cost dashboard**: four side-by-side sparkline cards (cost, tasks, latency, replay percent) with period-over-period deltas. Matches the mockup styling.

**Approvals tab**: shows only the active pending approvals for the current user's active task. Empty when nothing is gated.

**Memory view**: per-user bullets grouped by `memory_type` and `topic`, with decayed-strength rendered as a bar. Read-only; classmates cannot edit bullets directly.

**Audit log**: paginated table of `:AuditEntry` rows with user filter, date range, and completion-reason filter.

## 10. Cost and Budget

**Per-task cap**: `CUTIEE_MAX_COST_USD_PER_TASK=0.50` default.

**Per-hour cap**: `CUTIEE_MAX_COST_USD_PER_HOUR=5.00` default. Enforced via Neo4j `:CostLedger` MERGE with atomic hourly increment.

**Per-day cap (new)**: `CUTIEE_MAX_COST_USD_PER_DAY=1.00` default. Implemented as a daily aggregate across `:CostLedger` hourly rows keyed on `(user_id, day_key)`. Breach ends the run with `completionReason="cost_cap_reached:per_day"`.

**Cost dashboard math**: baseline = $0.30 per task (an operator choice reflecting industry norms for CU-capable agents without replay); savings counter = `(baseline * taskCount) - totalUsd`. The steady-state savings card on the sidebar uses this formula.

## 11. Neo4j Schema (Canonical)

Node labels:

- `:User {id, email, created_at}`: one per Google-authenticated classmate.
- `:Task {id, user_id, description, initial_url, created_at}`
- `:Execution {id, task_id, status, started_at, finished_at, completion_reason, total_cost_usd}`
- `:Step {id, execution_id, step_index, action_type, coordinate, cost_usd, risk, verification_ok, duration_ms, created_at}`
- `:AuditEntry {id, user_id, task_id, execution_id, step_id, timestamp, action_type, target, value_redacted, reasoning, model_used, tier, cost_usd, risk, approval_status, verification_ok, completion_reason}`
- `:Screenshot {execution_id, step_index, data_b64, size_bytes, created_at}`: 3-day TTL via background sweeper.
- `:MemoryBullet {id, user_id, memory_type, content, tags, topic, concept, semantic_strength, episodic_strength, procedural_strength, semantic_access_index, episodic_access_index, procedural_access_index, helpful_count, harmful_count, is_credential, is_seed, embedding, created_at}`: Phase 9 `bullet_user_scope` constraint requires `user_id IS NOT NULL`.
- `:ProceduralTemplate {id, user_id, topic, domain, stale, created_at}`
- `:CostLedger {user_id, hour_key, hourly_usd, created_at, updated_at}`
- `:ActionApproval {id, execution_id, user_id, status, reason, action_description, created_at, resolved_at}`
- `:PreviewApproval {execution_id, user_id, status, summary, created_at, updated_at, note}`
- `:ProgressSnapshot {execution_id, payload, updated_at, finished}`
- `:UserPrompt {id, user_id, task_id, content, created_at}`

Edges:

- `(User)-[:OWNS]->(Task)`
- `(Task)-[:EXECUTED_AS]->(Execution)`
- `(Execution)-[:HAS_STEP]->(Step)`
- `(Execution)-[:REPLAYED_FROM]->(ProceduralTemplate)`
- `(User)-[:HOLDS]->(MemoryBullet)`
- `(User)-[:RECEIVED]->(AuditEntry)`
- `(User)-[:SUBMITTED]->(UserPrompt)`

Constraints (bootstrapped at `agent/persistence/bootstrap.py`):

```
CREATE CONSTRAINT user_id           FOR (u:User)               REQUIRE u.id IS UNIQUE;
CREATE CONSTRAINT user_email        FOR (u:User)               REQUIRE u.email IS UNIQUE;
CREATE CONSTRAINT task_id           FOR (t:Task)               REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT execution_id      FOR (e:Execution)          REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT step_id           FOR (s:Step)               REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT bullet_id         FOR (b:MemoryBullet)       REQUIRE b.id IS UNIQUE;
CREATE CONSTRAINT bullet_user_scope FOR (b:MemoryBullet)       REQUIRE b.user_id IS NOT NULL;
CREATE CONSTRAINT audit_id          FOR (a:AuditEntry)         REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT cost_ledger_key   FOR (l:CostLedger)         REQUIRE (l.user_id, l.hour_key) IS UNIQUE;
CREATE CONSTRAINT action_approval_id   FOR (a:ActionApproval)    REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT preview_approval_id  FOR (p:PreviewApproval)   REQUIRE p.execution_id IS UNIQUE;
```

## 12. Configuration Surface

Required env vars at boot:

```
CUTIEE_ENV={local|production}
GEMINI_API_KEY=<string>
NEO4J_BOLT_URL=<bolt url>
NEO4J_USERNAME=<string>
NEO4J_PASSWORD=<string>
GOOGLE_CLIENT_ID=<string>
GOOGLE_CLIENT_SECRET=<string>
DJANGO_INTERNAL_DB_URL=<sqlite for Django internals only>
```

Optional env vars with documented defaults:

```
CUTIEE_CU_BACKEND={gemini|browser_use}           default: gemini
CUTIEE_CU_MODEL=<model id>                       default: gemini-flash-latest
CUTIEE_BROWSER_HEADLESS={0|1}                    default: 0
CUTIEE_BROWSER_CDP_URL=<http url>                default: unset (Xvfb + headful)
CUTIEE_STORAGE_STATE_PATH=<path>                 default: unset
CUTIEE_MAX_STEPS_PER_TASK=<int>                  default: 30
CUTIEE_MAX_COST_USD_PER_TASK=<float>             default: 0.50
CUTIEE_MAX_COST_USD_PER_HOUR=<float>             default: 5.00
CUTIEE_MAX_COST_USD_PER_DAY=<float>              default: 1.00
CUTIEE_HISTORY_KEEP_TURNS=<int>                  default: 8
CUTIEE_REPLAY_FRAGMENT_CONFIDENCE=<float>        default: 0.80
CUTIEE_ALLOW_URL_FRAGMENTS={0|1}                 default: 0
CUTIEE_HEARTBEAT_MINUTES=<int>                   default: 20
CUTIEE_REFLECTOR={heuristic|llm}                 default: heuristic
CUTIEE_REQUIRE_APPROVAL_HIGH_RISK={0|1}          default: 1
CUTIEE_SCREENSHOT_TTL_DAYS=<int>                 default: 3
CUTIEE_AUDIT_TTL_DAYS=<int>                      default: 30
```

Any value outside the allowed set for a closed enum raises at `Config.fromEnv()`.

## 13. Performance and Latency Targets

**Ten-step task duration**: target under 5 minutes end-to-end (p95). The heartbeat gate caps hard at 20 minutes regardless.

**Per-step latency (no replay)**: target under 30 seconds p95 including screenshot capture, model call, approval decision wait (auto-approve path), action execute, screenshot persist.

**Replay-fragment step latency**: target under 3 seconds p95 (no model call).

**Preview generation**: single CuClient call, capped at 500 output tokens, target under 10 seconds.

**Neo4j poll interval**: 1 second for `:PreviewApproval`, `:ActionApproval`, `:ProgressSnapshot`. Load scales linearly with active-task count.

No SLO commitments because the cohort is small; SPEC.md pins targets but the team does not commit to paging on breach.

## 14. Testing Strategy

**Coverage floor**: 80 percent line coverage on any new module. Measured via `pytest-cov`.

**Required test types for every new capability**:

1. Unit tests for pure functions (safety guards, reflector scrubbing, fragment matcher).
2. Integration tests against demo Flask sites in `demo_sites/`.
3. Replay round-trip test for any adapter that emits actions.
4. One live-smoke test per backend per release, gated behind `CUTIEE_EVAL_LIVE=1`.

**Pytest markers**: `local` (requires Neo4j + Mock client), `production` (requires real Gemini + Chromium), `integration` (demo sites), `showcase` (real-site storage_state fixtures).

**Eval harness**: `python -m agent.eval.webvoyager_lite --backend gemini --backend browser_use` runs three scripted tasks per backend against `demo_sites/` and emits a CSV + markdown summary. Run weekly during development.

## 15. Rollback and Recovery

**Primary mechanism**: Render commit-based rollback. Redeploy the prior commit through Render's UI; the platform swaps containers within 5-10 minutes.

**Neo4j migration policy**: every schema change is additive (new nodes, new constraints, new indexes). Never remove a field or rename a label without a two-step deprecation. This keeps rollbacks safe without data loss.

**Backup**: AuraDB Free retains point-in-time backups for 24 hours. Beyond that, operator is responsible for periodic manual exports.

**Recovery time objective**: 15 minutes for deploy failures, 1 hour for Neo4j incidents.

## 16. Observability

Minimal. The system intentionally does not ship Sentry, OpenTelemetry, or Prometheus.

**Log streams**: Render captures stdout and stderr from the web service and worker. That is the only runtime log.

**Durable query surface**: Neo4j itself. Every audit event, cost ledger row, and progress snapshot is queryable via Cypher. The Cost dashboard and Audit log tabs hit Neo4j directly.

**Alerts**: none. Classmates notice breakage through the UI; the instructor monitors the Render health tab and Neo4j query performance manually.

## 17. Known Limitations

These are deliberate scope deferrals documented for honesty.

- **No right-to-delete**: a classmate asking to remove all their data has no supported path. Manual deletion via AuraDB Bloom is possible but undocumented. Adding a compliant flow is tracked as future work.
- **Shared key pressure**: when the Render deployment runs on the instructor's Gemini key, per-user cost caps are the only defense against abuse. A determined classmate could still exhaust the daily budget by rotating identities.
- **VNC stability on slow networks**: noVNC over WebSocket is latency-sensitive. Classmates on weak connections may see the stream stutter; the `live_view_lost` abort will fire on extended loss.
- **No multi-tab automation**: the CDP tab fence (Phase 9) opens one fresh page. Tasks that require two coordinated tabs are not supported in this revision.
- **Single concurrent task per user**: matches "one at a time, strict". Users who submit back-to-back wait in a FIFO queue.
- **Plaintext Gemini key in .env**: acceptable for a cohort deployment; not acceptable for broader distribution. SPEC.md calls this out as a known gap for any future productization.

## 18. Non-Goals

SPEC.md is opinionated about what CUTIEE does not do.

- Not a public SaaS. Not hardened for adversarial users.
- Not a replacement for Selenium, Playwright, or browser-use standalone. CUTIEE adds memory, preview, audit, and replay on top of one of them.
- Not a training ground for novel CU models. Existing backends only.
- Not a data pipeline. Screenshots are operational, not research artifacts; the 3-day TTL is non-negotiable.
- Not a billing system. The cost dashboard informs; it does not invoice.

## 19. Glossary

- **ACE**: Agentic Context Engineering. The bullet-based memory pipeline with Reflect, Gate, Curate, Apply stages.
- **Bullet**: a single unit of learned knowledge. Three strength channels (semantic, episodic, procedural).
- **CDP**: Chrome DevTools Protocol. Lets the controller attach to a running Chrome or drive a fresh Chromium.
- **CuClient**: Protocol at `agent/routing/cu_client.py`. Both CU backends satisfy it.
- **Fragment replay**: Phase 15. Per-step replay that interleaves zero-cost reused actions with model calls where values are dynamic.
- **Preview**: Phase 16. A natural-language summary the user approves before any browser action fires.
- **Replay round-trip**: the hard contract requiring every adapter to emit canonical `ActionType` values that survive `_actionFromBullet` reconstruction.
- **Tier**: cost class on an action. Tier 0 is zero-cost (replay, fragment, harness navigation). Tier 1 is a paid model call.
- **VNC panel**: the main content area of the dashboard when a task is running. Renders a noVNC iframe pointing at the worker's websockify port.
