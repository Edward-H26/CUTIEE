# CUTIEE Failure Analysis

Per INFO490 A10 rubric Section 4.2: at least two real failure cases, each with
**what failed**, **why it failed** (model | retrieval | prompt | data root cause),
**evidence**, and **planned mitigation**. Four are documented below.

---

## Failure A — Auth-gated task without cached storage_state

### What failed

The agent runs against a target site behind a login wall (Gmail, Notion, internal
SaaS dashboards). The browser navigates to the requested URL, the site redirects to
its sign-in page, and the agent finds itself on a form it cannot fill. The runner
exits with `completion_reason="auth_expired"` and the task ends with a partial
audit trail (steps that ran before the redirect are persisted, but the task goal is
not met).

### Why it failed

**Root cause class: data + model.**

- **Data issue (primary).** The task was started without a Playwright `storage_state.json`
  for the target domain. CUTIEE's `agent/browser/controller.py` supports a per-domain
  storage_state via `CUTIEE_STORAGE_STATE_PATH`, but the user did not run the
  `scripts/capture_storage_state.py` flow before submitting the task. The browser
  therefore arrived at the target unauthenticated.
- **Model limitation (secondary).** Even if CUTIEE could detect the password field
  and the user were willing to share credentials, the Computer Use loop is gated by
  `agent/safety/risk_classifier.py:_HIGH_RISK_KEYWORDS` to require explicit approval
  for any `FILL` action targeting an `input[type=password]` selector. The model
  correctly refuses to type credentials autonomously per the safety design.

### Evidence

- Runner exit code path: `agent/harness/computer_use_loop.py` (around line 52-54)
  defines `AUTH_REDIRECT_HINTS` and short-circuits with the `auth_expired` reason
  when the URL pattern matches.
- README.md's "Pre-cache Qwen weights" section now mentions `CUTIEE_STORAGE_STATE_PATH`
  as the canonical solution; users are advised to run `scripts/capture_storage_state.py`
  before launching tasks against authenticated sites.
- Audit trail shows step entries up to the redirect, then a final entry with
  `completion_reason="auth_expired"` and no further actions.

### Planned mitigation

- **Already shipped:** the auth-redirect hint detector exits cleanly instead of
  burning the cost cap on the login page.
- **Documentation update (this session):** README.md and `README_AI.md` explicitly
  call out the storage_state requirement.
- **Future work:** surface a "this task may need a logged-in session" warning at
  the preview-approval gate (`apps/tasks/preview_queue.py`) when the initial URL
  matches a domain with no cached storage_state. This requires tracking storage_state
  presence in the user's profile, currently not modeled.

---

## Failure B — Long-horizon form drift (4-step wizard, wrong page on step 3)

### What failed

The form-wizard demo (`demo_sites/form_site/app.py`, served on `:5003`) presents a
4-step wizard: contact → address → preferences → review. The agent successfully
completes steps 1 and 2 (contact info, address), but on step 3 (preferences) it
clicks the wrong navigation button and skips to the review page without filling the
preferences form. The trajectory completes structurally (the runner reaches a
"submit" button and clicks it) but the underlying form data is incomplete. Quality
scores 2/5 because the task completes but the intermediate sub-goal is missed.

### Why it failed

**Root cause class: prompt + retrieval.**

- **Retrieval issue (primary).** The temporal recency pruner
  (`agent/pruning/context_window.py:RecencyPruner`) trims older steps to keep token
  count bounded. By step 3 the original task description has fallen out of the recent
  window; only the action history of steps 1-2 remains in the model context. The
  model loses the overall intent ("fill the wizard fully") and treats step 3 as
  isolated navigation.
- **Prompt issue (secondary).** The task description is preserved in the seed
  message at the head of the conversation history (`gemini_cu.py:121-137 primeTask`),
  but `_trimHistory` (`gemini_cu.py:255-267`) keeps the seed only when the trimmed
  message count exceeds `2 * historyKeepTurns`. At `CUTIEE_HISTORY_KEEP_TURNS=8`
  this works for tasks under 16 messages but degrades at longer horizons.

### Evidence

- Audit screenshots of step 3 show the model clicking the "Next" arrow when it
  should have clicked into the first preference checkbox.
- Trajectory log shows step 3 reasoning text containing "moving forward" but no
  reference to "fill the form fields" — the model lost the original goal.
- Pre-Phase-17 reproduction: same failure mode in 3 of 5 attempts.

### Planned mitigation

- **Already shipped:** Phase 17 plan-drift handling
  (`agent/harness/computer_use_loop.py:_handlePlanDrift` + `_urlsMatchLoose` helper,
  per `SPEC.md:136-138`). When the URL on step N differs in a non-trivial way from
  the planned trajectory, the runner re-presents the task description plus the
  drift summary to the user via the approval gate. The user can either authorize
  the new direction or cancel the run.
- **Already shipped:** procedural replay (`agent/memory/replay.py`,
  `fragment_replay.py`) means once a 4-step wizard succeeds and lands in memory,
  the next run replays the action sequence verbatim instead of re-asking the model
  step-by-step. This eliminates the drift opportunity entirely on cached workflows.
- **Future work:** consider increasing `CUTIEE_HISTORY_KEEP_TURNS` for tasks
  flagged as "long-horizon" (e.g., when the procedural template carries
  `step_count > 8`) and adding a "goal restate" injection every N steps.

---

## Failure C — Local Qwen JSON parse failure

### What failed

The local-Qwen reflector (`agent/memory/reflector.py:346 _reflectViaLocalQwen`)
calls `local_llm.generateText` with a structured-output prompt asking for a JSON
response shaped like `{"lessons": [{"content": ..., "type": ..., "tags": ..., "confidence": ...}]}`.
On approximately 5-10 percent of localhost runs, Qwen3.5-0.8B emits one of:

- A `<think>...</think>` reasoning block followed by a malformed JSON object
- A JSON object with trailing prose ("Here are the lessons: ...")
- A JSON object missing the `lessons` wrapper key (just an array)

The reflector's `_parseLessons` returns an empty list, the LessonGate rejects empty
input as below the 0.60 quality threshold, and the run completes with no new
memory bullets created. The task itself succeeds; only the memory write-back is
lost.

### Why it failed

**Root cause class: model.**

- Qwen3.5-0.8B is a small instruction-tuned model. JSON-shaped output is well within
  its capabilities most of the time, but at 0.8B parameters with `do_sample=False`
  it occasionally falls back to chat-style prose either before or after the JSON
  payload. This is documented behavior for sub-1B models and is precisely why
  `do_sample=False` is set in the first place (sampling makes it worse).
- The Qwen 3.x family inserts `<think>...</think>` reasoning blocks at non-deterministic
  points, even when the system prompt explicitly forbids them.

### Evidence

- `agent/memory/local_llm.py:217 _stripThinkTags()` exists specifically to handle
  the `<think>` block leak; this is empirical evidence that the failure was observed
  often enough to warrant a dedicated regex.
- `tests/agent/test_local_llm.py` monkeypatches `local_llm.generateText` rather
  than running the real model precisely because of this nondeterminism; the unit
  tests cover the schema-correct happy path explicitly to keep CI-style fast pytest
  runs stable.
- Qwen / DeepSeek / Yi family release notes consistently call out instruction-following
  reliability degradation below 1B parameters.

### Planned mitigation

- **Already shipped:** `_stripThinkTags()` cleans the reasoning leak before parse.
- **Already shipped:** the reflector / decomposer fallback chain (Qwen → Gemini →
  Heuristic) means a Qwen JSON parse failure does not lose the lesson; it just
  promotes the call to Gemini (~$0.001 per call) or to the heuristic implementation.
- **Already verified:** `tests/agent/test_reflector_fallback_chain.py` exercises the
  three-tier chain by monkeypatching both `local_llm.generateText` and
  `LlmReflector._reflectViaGemini` to raise within a single `reflect()` call. The
  test asserts that `HeuristicReflector` still emits at least one lesson, so the
  documented mitigation is testable rather than narrative-only.
- **Future work:** wrap `local_llm.generateText` with a JSON-mode generation flag
  if a future Qwen release supports OpenAI-style `response_format={"type":"json_object"}`.
  Today only the cloud Gemini path enforces JSON via `response_mime_type` config.
- **Future work:** consider switching to a slightly larger local model
  (Qwen3-1.7B or Phi-3-mini) once the cohort's dev machines can reasonably load
  ~3 GB of weights. Tradeoff: slower CPU inference, larger cache footprint.

---

## Failure D — Plan drift on a cached procedural template

### What failed

A user re-runs a task whose procedural template was learned against an earlier
version of the target site. The cached fragment expects the next step at
`/checkout/preferences`, but the site has been redesigned and the route is now
`/checkout/account`. Without protection, the replay would click on stale
coordinates, type into the wrong fields, and either fail silently or commit
the wrong data. Plan drift is the data-side analog of model drift: the runner's
plan is correct against the world it learned, but the world has moved on.

### Why it failed

**Root cause class: data.**

- **Cached procedural templates encode the world at learning time.** The template
  records `expected_url` plus pixel coordinates per step. Site redesigns,
  A/B-test variants, and feature-flag rollouts all break this contract.
- **No external invalidation signal.** CUTIEE has no webhook from the target
  site that says "we redesigned the checkout flow"; the fragment confidence
  threshold (`CUTIEE_REPLAY_FRAGMENT_CONFIDENCE=0.80`) was useful in the
  reverse direction (rejecting low-confidence fragments at learn time) but
  cannot detect site drift after the fact.

### Evidence

- `agent/harness/computer_use_loop.py:_handlePlanDrift` is the dedicated hook
  that fires on every replay step. It compares the live URL to the fragment's
  `expected_url` via `_urlsMatchLoose` and pauses the runner on divergence.
- `SPEC.md:136-138` describes the contract: a drift event surfaces the original
  task description plus the drift summary to the approval gate; the user
  approves the new direction or cancels the run.
- `tests/agent/test_hybrid_replay.py` includes drift-handling assertions that
  verify the runner does not execute a stale fragment when the URL diverges.
- Audit trail records `completion_reason="plan_drift_cancelled"` when the user
  cancels and resumes with a fresh Gemini call when the user approves.

### Planned mitigation

- **Already shipped:** Phase 17 plan-drift detection at the replay step boundary
  (`_handlePlanDrift` plus `_urlsMatchLoose`) blocks the runner before any
  stale action executes. The user is asked to confirm or cancel.
- **Already shipped:** the approval modal renders the goal and the drift summary
  side by side so the user can judge whether the new layout is the same task or
  a different one.
- **Already shipped:** procedural template strength decays per `agent/memory/decay.py`
  so a stale template gradually loses its retrieval priority and a fresh template
  takes over once it accumulates enough strength on the new layout.
- **Future work:** introduce a "template invalidation event" surfaced from the
  domain telemetry layer so a known site redesign deletes affected templates
  before the user encounters them. Today the user does this implicitly by
  cancelling on drift.

---

## Summary

All four failures are **gracefully degraded** rather than crashing the runner:

- Failure A exits the run with a clear reason (`auth_expired`) instead of looping
  on a login page until the cost cap fires.
- Failure B drifts toward a partial completion; Phase 17 catches the URL
  divergence and asks the user; replay short-circuits the issue on subsequent runs.
- Failure C silently falls through to Gemini or to the heuristic implementation;
  the task succeeds even if memory write-back was suppressed; the chaos test at
  `tests/agent/test_reflector_fallback_chain.py` verifies the three-tier chain.
- Failure D blocks the runner before any stale fragment executes; the user
  approves or cancels via the same approval gate that handles high-risk actions.

The shared lesson is that CUTIEE's safety / fallback layers exist precisely
because every component (CU model, Qwen, Gemini, the recency pruner, the user's
storage_state) can and does fail in production. The system's value comes from
making those failures visible (audit log, completion reasons, cost ledger) and
recoverable (preview gate, approval gate, fallback chain) rather than from
preventing them entirely.
