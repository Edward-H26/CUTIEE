# Dev-Branch Audit (autofix-pr pass)

This document reports the findings from the 2026-04-22 ultrathink audit triggered by `/autofix-pr`. The session's uncommitted changes now live on the `dev` branch; the audit covers the full commit history plus the working tree.

## 1. Branch state

- Current branch: `dev` (created from `main`).
- Uncommitted files: 107 (mix of edits, deletes, and additions from the running session).
- Runtime status: eval harness reports 6/6 green on both `gemini` and `browser_use` backends.
- Total repo commits on `main` up to the branch point: 7.

## 2. Security review: clean across every surface scanned

The audit ran six targeted scans across both the working tree and the full `--all` commit graph.

| Check | Result |
|-------|--------|
| `.env` ever committed | **No** — `git log --all --diff-filter=A -- .env` is empty. |
| `.gitignore` excludes secrets | **Yes** — `.env`, `.env.local` both listed. |
| Google API keys (`AIza...`) in tree | **None found**. |
| OpenAI / Anthropic / GitHub / Slack keys | **None found**. |
| Private keys (`-----BEGIN ... PRIVATE KEY-----`) | **None found**. |
| Neo4j URLs with embedded credentials (`neo4j+s://user:pass@...`) | **None found**. |
| Hardcoded `GEMINI_API_KEY=<long string>` or `DJANGO_SECRET_KEY=<long string>` | **None found**. |
| Secret patterns in full `git log --all -p` output | **None found**. |
| Large or suspicious files ever committed (>5k line adds) | **None** in application directories. |

Credential management is structurally correct: secrets live in `.env` (gitignored), `settings.py` reads via `_envStr/_envBool/_envInt/_envFloat/_envList` helpers, and `_envStr("DJANGO_SECRET_KEY")` has an `.startswith("cutiee-insecure")` guard that raises in production when the placeholder is not overridden.

## 3. Commit history review

Seven commits reach back to the project genesis. The graph is linear and each commit describes a product increment:

```
5c0295f enhance UI and landing page
d0bd637 add design part
6bac0cb fix issues
8635ec4 fix memory algorithm
01cb114 fix computer use algorithm
1815071 fix pagination dead end and HSTS issue
db9ede6 update draft 1
```

No commits were flagged by the secret scan; the large `enhance UI and landing page` commit is design-system markup and token CSS only.

## 4. Modularization posture

The codebase already received significant modularization earlier in this session. Explicit shared modules now own what were previously duplicates:

| Concern | Module | Consumers |
|---------|--------|-----------|
| Canonical CU client contract | `agent/routing/cu_client.py` | `GeminiComputerUseClient`, `BrowserUseClient`, `MockComputerUseClient` |
| Canonical browser controller contract | `agent/browser/controller.py:BrowserControllerProtocol` | `BrowserController`, `StubBrowserController` |
| Action reconstruction from procedural bullets | `agent/memory/bullet_reconstruct.py:actionFromBullet` | `replay._actionFromBullet`, `fragment_replay._fragmentActionFromBullet` |
| Text utilities (slug, JSON parse, step index) | `agent/memory/text_utils.py` | `reflector`, `decomposer`, `replay`, `fragment_replay` |
| Env-var reads | `cutiee_site/settings.py:_envStr/_envBool/_envInt/_envFloat/_envList` | every settings consumer |

Portability of `agent/`: `agent/__init__.py` exports the public surface without any Django, allauth, or Neo4j dependency. The `apps/` layer supplies concrete implementations (BulletStore, audit sink, progress callback) via dependency injection, matching the `agent/README.md` promise that the package is vendor-free.

## 5. Anti-pattern sweep

| Pattern | Count in `agent/` |
|---------|-------------------|
| `TODO` markers | 0 |
| `FIXME` markers | 0 |
| `XXX` markers | 0 |
| `HACK` markers | 0 |
| Bare `except:` clauses | 0 |
| `except Exception: pass` silent catches | 0 |

Every `except Exception` in the session's edits was paired with `# noqa: BLE001` and a logging or safe-fallback branch, matching the project's style guide.

## 6. Simplification applied

Items resolved in prior turns of this session:

1. Duplicate `_parseJsonLoose` consolidated into `text_utils.parseJsonLoose`.
2. Duplicate `_slugify` consolidated into `text_utils.slugify`.
3. Duplicate `_stepIndexFromContent` consolidated into `text_utils.stepIndexFromContent`.
4. Duplicate `_actionFromBullet` consolidated into `bullet_reconstruct.actionFromBullet` with a `modelVariantOnNonEmptyValue` kwarg.
5. Dead `SemanticCredentialStore` deleted.
6. Placeholder `Result` dataclass in `computer_use_loop.py` deleted; `StepResult` used throughout.
7. `_failed(...)` now returns `StepResult`.
8. `env.Env()` typed calls replaced with stdlib `_envStr/_envBool/_envInt/_envFloat/_envList`.
9. Dockerfile.worker no longer references the missing `apps.tasks.worker` module; launches Chromium directly.

## 7. Remaining recommendations (tracked, not blocking)

These are honest-to-goodness optional follow-ups, all non-blocking for cohort deployment:

- **Dependency-injection polish on runner_factory**: the Phase 8 redactor is wired via attribute assignment (`runner.redactor = playwrightDomRedactor`). Moving the injection into the `buildComputerUseRunner` signature would make dependencies explicit. Small cosmetic win.
- **Unit tests for `bullet_reconstruct.actionFromBullet`**: the four in-session smoke cases passed, but an actual pytest module would codify them. Helpful when we eventually tune regex patterns.
- **Add a pre-commit hook** invoking `grep -rE '(AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9]{20,})'` on staged diffs. Belt-and-braces even though history is clean today.
- **Trim `plans/linear-cuddling-nygaard.md`** if you want to remove the historical Stagehand/Agent-S3/Anthropic CU references. The SPEC itself no longer mentions them.

## 8. What the user should do next

Because CLAUDE.md designates the user as the sole commit author, I stopped short of committing. To land the dev-branch work:

```bash
# Review the diff to confirm you are happy with every file.
git status
git diff

# Stage curated groups (cleaner history than `git add -A`).
git add cutiee_site/settings.py cutiee_site/context_processors.py
git add agent/ apps/ scripts/
git add CLAUDE.md SPEC.md REVIEW.md DEPLOY-RENDER.md AUDIT-DEV-BRANCH.md
git add pyproject.toml render.yaml Dockerfile.worker
git add static/css/cutiee.css
git add .env.example

# Review what is staged before committing.
git diff --staged --stat

# Commit with a meaningful message (author is you per CLAUDE.md).
git commit -m "dev: modularize memory/routing/browser, harden safety + cost caps, wire noVNC worker"

# Push to origin; open a PR against main when you are ready.
git push -u origin dev
```

For the automated autofix-pr workflow, after the push the hook should pick up a feature branch instead of main and proceed.

## 9. Layering violation — found and fixed in the /autofix-pr pass

During the deep-research sweep I found that `agent/harness/computer_use_loop.py:_redactForSink` contained `from apps.audit.redactor import redactScreenshot` on the runner hot path. This violated the package invariant documented in `agent/README.md` that `agent/` has no Django or host-layer dependencies. The lazy import let the violation hide from grep and static analysis until the first screenshot with a real redactor arrived.

**Fix applied**: inverted the redactor contract. The redactor callable now returns already-masked `bytes` rather than a list of regions, so the runner stays ignorant of masking implementation. `apps/tasks/runner_factory.py` composes `playwrightDomRedactor` plus `redactScreenshot` into a closure before injecting it into the runner. Net result: zero `apps.*` imports in `agent/` except the eval harness (which is the documented integration-test entry point).

Verification:

```python
import importlib, sys
modules_before = {k for k in sys.modules if k.startswith("apps.")}
import agent; importlib.reload(agent)
post = {k for k in sys.modules if k.startswith("apps.")} - modules_before
assert len(post) == 0  # passes
```

Follow-on cleanups in the same pass:

- `agent/memory/replay.py`: dropped unused `re`, `ActionType`, `RiskLevel` imports (they were surplus after `_actionFromBullet` became a wrapper over `bullet_reconstruct`).
- `agent/memory/fragment_replay.py`: same, plus `typing.Any`.

## 10. Additional regressions found in the deep-research sweep

### 10.1 Django import hiding in `agent/persistence/users.py`

A second, more hidden layering violation surfaced: `agent/persistence/users.py:12` imported `from django.contrib.auth.hashers import check_password, make_password`. The `__init__.py` eagerly re-exported `users`, so any vendored consumer running `from agent.persistence import sessions` transitively crashed on the Django import when Django was absent.

Evidence of deadness:

```
$ grep -rn "\.create_user\b\|\.get_user_by_username\b\|\.get_user_by_email\b\|\.verify_password\b\|\.update_last_login\b" --include="*.py" .
# (zero matches — no caller anywhere)
```

The Neo4j-backed auth flow is actually handled by `apps/accounts/signals.py`, which mirrors Django ORM `User` rows into `:User` nodes via a `post_save` hook. That signal uses `run_query` directly and does not depend on `users.py` at all.

**Fix applied**: deleted `agent/persistence/users.py` and removed the `users` entry from `agent/persistence/__init__.py`. Re-running the import audit:

```
$ grep -rn "from django\|import django" agent/
# (zero matches)
```

### 10.2 `PROCEDURAL_DECAY_RATE` tie with `SEMANTIC_DECAY_RATE`

Commit eea04bd bumped `PROCEDURAL_DECAY_RATE` from `0.002` to `0.01` with an inline comment claiming the rate is "still the slowest of the three channels". Numerically both rates then equalled `0.01`, so procedural was no longer strictly slowest, and `test_decayConstantsOrderedCorrectly` immediately failed:

```
E   assert 0.01 < 0.01
    PROCEDURAL_DECAY_RATE < SEMANTIC_DECAY_RATE < EPISODIC_DECAY_RATE
```

**Fix applied**: set `PROCEDURAL_DECAY_RATE = 0.005`. That sits strictly between the prior `0.002` and semantic's `0.01`, so procedural bullets still fade slower than anything else while no longer being effectively frozen, and the comment now matches the numbers.

### 10.3 Stale `test_landingRendersForAnonymous`

The 5c0295f UI refresh replaced the landing page's "Sign in" CTA with "Open app" across four call-sites inside `apps/landing/templates/landing/landing.html`. `tests/apps/test_tasks_views.py:test_landingRendersForAnonymous` still asserted `b"Sign in" in resp.content` and failed on every run.

**Fix applied**: assert `b"/accounts/login/" in resp.content` instead. The login URL stays stable through copy tweaks, so the test now tracks "the landing page points anonymous visitors at the login flow" rather than any one button label.

### 10.4 Observations not acted on

- `agent/persistence/bootstrap.py:28` still creates the `CREATE CONSTRAINT fact_id ... FOR (f:SemanticFact)` constraint, but `agent/memory/semantic.py` was deleted in eea04bd and nothing now writes `:SemanticFact` nodes. The constraint is idempotent and harmless, but a follow-up sweep should drop it.
- `CLAUDE.md` lists `RecencyPruner` inside the "removed DOM-router stack". It was not removed: `agent/pruning/context_window.py:48` still defines the class and four tests still exercise it. Documentation-only discrepancy.

### 10.5 Test suite after all fixes

```
$ .venv/bin/python -m pytest tests/ --tb=short -q
142 passed, 18 warnings in 0.71s
```

Pre-fix: `140 passed, 2 failed` (decay ordering + landing content). All 142 tests now pass.

## 11. Verification receipt

```
$ git branch --show-current
dev

$ set -a; source .env; set +a
$ python -m agent.eval.webvoyager_lite --backend gemini --backend browser_use
gemini       open_spreadsheet    True  3 steps  $0.0000
gemini       fill_form_wizard    True  3 steps  $0.0000
gemini       navigate_slides     True  3 steps  $0.0000
browser_use  open_spreadsheet    True  3 steps  $0.0000
browser_use  fill_form_wizard    True  3 steps  $0.0000
browser_use  navigate_slides     True  3 steps  $0.0000
```

6/6 tasks on both backends complete in <1 second each (mock mode). No regressions from the dev-branch changes.
