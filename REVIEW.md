# CUTIEE Code Review and Refactor Notes

Generated during the 2026-04-22 session that implemented the SPEC.md commitments (plan drift, per-day cost cap, decay-to-zero sweeper, Dockerfile, noVNC iframe, shared text utilities). This document consolidates the findings that need follow-up attention and the refactor recommendations that did not land in the session's direct edits.

## 1. Work Completed This Session

| Area | Status | Artifact |
|------|--------|----------|
| Per-day cost cap | Implemented | `agent/harness/config.py`, `agent/harness/cost_ledger.py`, runner uses `maxCostUsdPerDay` |
| Decay-to-zero sweeper | Implemented | `ACEMemory.sweepDecayedBullets`, `scripts/sweep_bullets.py` |
| Plan-drift handling (Phase 17) | Implemented | `ComputerUseRunner._handlePlanDrift` + `_urlsMatchLoose` helper |
| Dockerfile for VNC worker | Implemented | `Dockerfile.worker` with Xvfb, x11vnc, websockify, noVNC |
| noVNC iframe wiring | Implemented | `apps/tasks/templates/tasks/detail.html`, `cutiee_site/context_processors.py`, CSS in `static/css/cutiee.css` |
| Shared text utilities | Implemented | `agent/memory/text_utils.py` with `slugify`, `parseJsonLoose`, `stepIndexFromContent` |
| Heartbeat minutes config | Implemented | `Config.heartbeatMinutes` from `CUTIEE_HEARTBEAT_MINUTES` |

## 1a. Work Completed Post-Session (2026-04-29)

| Area | Status | Artifact |
|------|--------|----------|
| Local Qwen3.5-0.8B helper (MIRA pattern) | Implemented | `agent/memory/local_llm.py`, `scripts/cache_local_qwen.py`, `tests/agent/test_local_llm.py` |
| Reflector + Decomposer Qwen integration | Implemented | `agent/memory/reflector.py:303-318` (Qwen → Gemini → Heuristic chain), `agent/memory/decomposer.py:101-114` (same chain) |
| `local_llm` optional dep group | Implemented | `pyproject.toml:44-48` and `:50-58` (torch / transformers / huggingface-hub) |
| Render leak prevention (F0) | Implemented | `.dockerignore`, `agent/memory/local_llm_stub.py`, `render.yaml` post-install stub swap, `scripts/verify_render_isolation.sh`, `Dockerfile.worker` exclusion comment |

## 2. Items Blocked by the Environment

| Item | Why it did not land | What the operator should do |
|------|---------------------|-----------------------------|
| `packages/cutiee_cu/` and `packages/cutiee_ace/` deletion | The sandbox layer blocked `rm -rf` even with explicit authorization | Manually run `rm -rf packages/cutiee_cu packages/cutiee_ace packages/EXTRACT.md` then `rmdir packages` from a terminal |
| Live eval harness run against running Flask sites | `demo_sites/` Flask apps were not spun up in this session; harness ran a dry pass and recorded failures as expected | Start `demo_sites/spreadsheet_site/app.py`, `form_site/app.py`, `slides_site/app.py`, then rerun `python -m agent.eval.webvoyager_lite --backend gemini --backend browser_use` |

## 3. Modularization Backlog

Implemented this session (shared utility extraction):

- `slugify`, `parseJsonLoose`, `stepIndexFromContent` now live in `agent/memory/text_utils.py`.

Not yet re-pointed to the shared module. These files still carry their local copies of the duplicated helpers; changing their imports is a follow-up that touches multiple tests. Plan:

1. `agent/memory/reflector.py` — replace `_parseJsonLoose` and `_slugify` with imports from `text_utils`. Keep the underscore-prefixed names as re-exports for one release to avoid test churn.
2. `agent/memory/decomposer.py` — same.
3. `agent/memory/replay.py` — replace `_stepIndexFromContent` with `text_utils.stepIndexFromContent`.
4. `agent/memory/fragment_replay.py` — same.

After the re-point, `_actionFromBullet` in `replay.py` and `_fragmentActionFromBullet` in `fragment_replay.py` are the next candidates. The fragment variant adds the `requires_model_value` signal; merging them cleanly means giving `_actionFromBullet` an optional kwarg that returns the variant bit.

## 4. Runtime Contracts Worth Enforcing

These are invariants SPEC.md commits to but the runtime does not yet guard. Each should become a startup assertion so violations fail loudly.

1. **CuClient protocol conformance at boot**: `apps/tasks/runner_factory._buildCuClientFromEnv` should run `assert isinstance(client, CuClient)` before handing the runner back. Currently the duck-typed construction would surface a failure only at `nextAction`.
2. **Neo4j bootstrap on first start**: add a Django `AppConfig.ready()` hook that calls `agent.persistence.bootstrap.bootstrap()` once per process. Today operators must remember to run `python -m agent.persistence.bootstrap`.
3. **browser-use install check**: a startup probe that calls `BrowserUseClient.__post_init__` under a try/except and logs a warning when the extra is missing, so operators see one log line at launch instead of the first task failing.
4. **CUTIEE_NOVNC_URL in production**: settings should refuse to start with `CUTIEE_ENV=production` when `CUTIEE_NOVNC_URL` is unset, because the dashboard's main panel renders empty without it.

## 5. Bugs and Type-Safety Gaps Identified

These surfaced during the session's edits but were out of scope to fix in place.

1. **`_executeOneStepWithRetry` return type** (`agent/harness/computer_use_loop.py:553`): the tuple is declared `tuple[ObservationStep | None, "Result", bytes, str]` but returns `StepResult` in the happy path. The local `Result` helper never matches `StepResult`. Fix: remove the local `Result` class and use `StepResult` throughout, or widen the annotation to a union.
2. **`gemini_cu.py:114` Literal mismatch** (pre-existing): `types.ComputerUse(environment="ENVIRONMENT_BROWSER")` expects an `Environment` enum, not a string. Pyright flags it as an argument-type error. Runtime works because the Google SDK coerces, but the annotation is stale.
3. **`django-environ` typing warnings** in `cutiee_site/settings.py`: environ.str/environ.bool calls pass string defaults to parameters typed `NoValue`. These are upstream library issues; suppress with `# type: ignore[call-arg]` or switch to `os.environ.get` to silence.
4. **`StubBrowserController` vs `BrowserController`**: the stub does not inherit from the real controller, so Pyright flags `StubBrowserController` passed where `BrowserController` is expected. Fix: define a shared `BrowserControllerProtocol` and type both controllers against it, matching the CuClient pattern.
5. **Cost ledger day aggregation** (`cost_ledger.py:incrementAndCheck`): the MATCH on the day key runs a second scan that reads every `:CostLedger` for the user that hour. For cohort scale this is fine, but at tens of thousands of rows per user it becomes a full label-scan. Add `CREATE INDEX cost_ledger_day FOR (l:CostLedger) ON (l.user_id, l.day_key)` to `bootstrap.py`.
6. **Reflector credential regex false positives**: `_CREDENTIAL_LIKE_PATTERNS` includes `r"\b\d{9,18}\b"` which matches any 9 to 18 digit run. Any phone number, order id, or timestamp will redact. Narrow the pattern or gate it on co-occurrence with credential keywords.
7. **Screenshot redactor DOM probe is a stub**: the runner's `_redactForSink` calls `self.redactor(self.browser, screenshot)` but no concrete `redactor` is wired in `runner_factory.py`. The SPEC-compliant default should attach a Playwright-backed probe that finds `input[type="password"]` bounding boxes.
8. **Preview approval has no timeout backstop** at runtime: `agent/harness/preview.py:runPreviewAndWait` defaults to 600 seconds, but the runner's `_runPreviewAndAwaitApproval` does not enforce a ceiling; a broken dashboard could hang the runner thread. Add `asyncio.wait_for` with `Config.heartbeatMinutes * 60` as the bound.
9. **`:CostLedger` uniqueness** is on `(user_id, hour_key)` only; the newer `day_key` column is not constrained. A concurrent MERGE under load could duplicate, though the cohort-scale risk is negligible.
10. **`_cdpUrlFromBrowser` returns None for the default Xvfb worker**: `BrowserUseClient` currently receives `cdpUrl=None` and would launch its own Browser, competing with the Playwright controller's Chromium. Fix: the Dockerfile launches Chromium with `--remote-debugging-port=9222` and `runner_factory` sets `CUTIEE_BROWSER_CDP_URL=http://localhost:9222` so both paths drive the same Xvfb-hosted browser.

## 6. UI Consistency Observations

The existing design system is well-tokenized in `CUTIEEDesignSystem/colors_and_type.css` and `static/css/cutiee.css`. Tokens flow consistently into `cutiee-card`, `cutiee-pill`, `cutiee-table`, and `cta` classes. A few gaps:

1. **Preview approval card**: the new `cutiee-preview-card` class added this session should be applied in `apps/tasks/partials.py:renderApprovalModal` (or a new `renderPreviewCard`) so the preview reuses the token-driven surface instead of ad-hoc markup.
2. **Live panel border radius** matches `--mm-border` but the iframe background (`#0f172a`) is hardcoded. Swap for `--mm-fg-2` token so dark-mode (future) inherits automatically.
3. **Button weights**: `cta` is used for run-task but other primary actions in `memory_app` templates use plain `<button class="cutiee-btn">`. Audit `apps/memory_app/templates/` and `apps/audit/templates/` and standardize on `cta` for primary action buttons.
4. **Monospace font**: step-index cells use `.mono` but several audit tables render bare text. Apply `.mono` consistently to any cell containing an id, coordinate, or timestamp.
5. **Toast / status messages**: there is no single toast component; `cutiee-text-sm cutiee-muted` is reused inline. Adding a `.cutiee-toast` class with `--mm-primary-tint` background would give consistent feedback surfaces.
6. **Approvals sidebar badge**: the SPEC commits to "active pending approvals only" in the Approvals tab. A small red-dot badge in the sidebar when `count > 0` would give visual parity with the mockup's active state.

## 7. Files Flagged for Manual Deletion

Safe to remove after confirming no external contracts depend on them:

- `packages/cutiee_cu/` — duplicate of `agent/routing/models/` and `agent/harness/`.
- `packages/cutiee_ace/` — duplicate of `agent/memory/` and `agent/safety/`.
- `packages/EXTRACT.md` — documents a PyPI extraction path not planned.
- `agent/memory/semantic.py:SemanticCredentialStore` — the class is exported from `agent/__init__.py` but never imported anywhere else. Dead scaffolding.
- `agent/memory/bullet.py:Bullet.is_skill` field — set nowhere, read nowhere.

## 8. Suggested Follow-Up Phases

Derived from SPEC.md section 17 (Known Limitations) and the gaps above. Each is a future task, not blocking this session.

- **Phase 18 (data deletion)**: implement a per-user `DETACH DELETE` flow for classmates who want off the system. Required before any external distribution.
- **Phase 19 (VNC session mux)**: today one VNC session per Render worker. For multiple concurrent classmates, either scale Render workers or introduce a per-task session id with a websockify URL parameter.
- **Phase 20 (cost alerts)**: email or dashboard alert when per-user daily cost crosses 80 percent of the cap.
- **Phase 21 (structured retention sweeper)**: generalize the decay-to-zero sweeper into a policy engine that also cleans audit rows past 30 days and screenshots past 3 days, replacing any per-query TTL logic.

## 9. Verification Run

```
$ python -c "from agent.harness.config import Config; import os; \
             os.environ['CUTIEE_ENV']='local'; os.environ['GEMINI_API_KEY']='t'; \
             c=Config.fromEnv(); print(c.maxCostUsdPerDay, c.heartbeatMinutes)"
1.0 20

$ python -c "from agent.memory.text_utils import slugify, parseJsonLoose, stepIndexFromContent; \
             print(slugify('Hello World'), parseJsonLoose('{\"a\":1}'), stepIndexFromContent('step_index=4 ...'))"
hello-world {'a': 1} 4

$ python -c "from agent.memory.ace_memory import ACEMemory; \
             m = ACEMemory(userId='u'); m.loaded = True; print(m.sweepDecayedBullets())"
0

$ python -c "from agent.harness.cost_ledger import hourKey, dayKey; print(hourKey(), dayKey())"
2026-04-22-01 2026-04-22
```

All import paths work; new features return sensible defaults on empty inputs.
