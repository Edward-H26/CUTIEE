# CUTIEE Technical Report

## Overview

CUTIEE is a Django web application that wraps a computer-use agent with
three cost-reduction mechanisms and a self-evolving memory subsystem. The
application demonstrates a viable consumer-grade computer-use pipeline by
turning recurring tasks into zero-inference replays, keeping the
per-step prompt budget bounded as tasks lengthen, and routing each
decision to the cheapest viable model. The persistence layer uses Neo4j
for every domain entity, including users, sessions, tasks, executions,
steps, memory bullets, procedural templates, and audit entries.

## Architecture

### Layered responsibilities

The repository separates a Django web layer from a plain-Python agent
package:

- `cutiee_site/` holds settings, URL routing, and a Neo4j-backed session
  engine.
- `apps/` contains the user-facing Django apps. Each app exposes a
  Cypher-backed repository module rather than a Django ORM model.
- `agent/` contains the agent runtime. Subpackages map one-to-one to the
  three mechanisms: `memory/`, `pruning/`, `routing/`, plus `harness/`,
  `browser/`, `safety/`, and `persistence/`.

The two layers meet at `apps.tasks.services.runTaskForUser`, which builds
the appropriate orchestrator for the active `CUTIEE_ENV`, runs the task,
and persists the resulting `AgentState` back through the repos.

### Environment switch

`CUTIEE_ENV` is a hard switch. `local` mode wires the router to three
Qwen3.5 0.8B clients with three different prompt budgets. `production`
mode wires the router to three Gemini 3.1 variants. Missing the variable
raises at settings import time, and missing the environment-specific
secrets raises before the first task runs.

### Persistence

Every domain entity lives in Neo4j as a labelled node with explicit
relationships. The label namespace is `:User`, `:Task`, `:Execution`,
`:Step`, `:MemoryBullet`, `:ProceduralTemplate`, `:AuditEntry`, and
`:Session`. Constraints are installed by `agent.persistence.bootstrap`
and are idempotent so the same script runs safely on every deploy.

## Three mechanisms

### Procedural memory replay

After every successful run, the reflector emits one structured
procedural-type bullet per step. The bullets cluster by `topic`, which is
derived from a slug of the task description. The `ReplayPlanner`
retrieves bullets above the match threshold (default 0.85), reconstructs
an ordered action list, and `ComputerUseRunner._executeReplay` runs those
actions through the browser without invoking the model. A failed replay
step finalizes the run as `replay_failed`, decreasing the bullet's
procedural strength so the next attempt prefers a fresh CU pass.

### Two-tier cost model

After the 2026-04 pivot to screenshot-everywhere, the tier system collapsed
to two semantic states:

- **Tier 0 — zero cost.** Memory replay (`model_used="replay"`) and
  harness-emitted browser navigation (`model_used="harness"`). No model
  call happens.
- **Tier 1 — Computer Use.** Every step that calls the Gemini ComputerUse
  tool. Default model is `gemini-flash-latest`; pin to
  `gemini-3-flash-preview` via `CUTIEE_CU_MODEL` for deterministic replay.

The dashboard's tier-distribution chart now answers a simpler question:
"how often did procedural memory save us a model call?"

## Self-evolving memory

The memory subsystem implements the ACE loop:

```
trace -> Reflector -> QualityGate (>= 0.60) -> Curator -> DeltaUpdate -> apply -> refine
```

The reflector emits `LessonCandidate`s typed as semantic, episodic, or
procedural. The quality gate combines `output_valid`, average lesson
quality, and average confidence into a single score; runs that fall
below 0.60 or whose top lesson scores under 0.70 confidence are rejected
with diagnostics. The curator deduplicates against the existing bullet
store, increments `helpful_count` on hits, and emits new bullets for
genuine novelties. Every bullet carries three independent strength
channels with per-channel exponential decay.

## Safety

`classifyRisk` runs a keyword sweep over the action target, value,
reasoning, and surrounding task text. High-risk actions are gated by
`ApprovalGate`, which is async and channel-agnostic. The orchestrator
awaits the gate before executing the action; if the user rejects, the
run aborts with `completionReason="rejected_by_user"`. Every step is
written to `:AuditEntry` via `agent.safety.audit.buildAuditPayload`.

## Failure policy

The system never falls back silently. Missing dependencies, missing
model files, missing API keys, an unset `CUTIEE_ENV`, an unreachable
Neo4j endpoint, and an unreachable VLM endpoint all raise a clear
`RuntimeError` with actionable remediation text.

## Production posture

Render deployment uses the spec in `render.yaml`. Gunicorn serves the
Django app with Whitenoise for static assets. The Django framework
tables migrate into the SQLite path defined by
`DJANGO_INTERNAL_DB_URL` on every process boot. Neo4j AuraDB Free
provides the persistent graph; constraints reapply via the bootstrap
command. Browser automation runs headless via Playwright, but the
default deployment uses the `StubBrowserController` so the web tier
doesn't need browser binaries; a separate worker tier handles real
browser sessions when needed.

## Limitations

The progress cache is process-local; horizontal scaling on Render
requires Redis as the shared progress backend. Embeddings default to a
hash-based fallback so the application boots without FastEmbed; the real
encoder is loaded only when the operator explicitly opts in. Pricing
constants for Gemini 3.1 are estimates pending Google's final tier
publication; updating `PRICING_PER_MILLION` is a one-line change.
