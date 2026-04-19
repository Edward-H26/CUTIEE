# `agent/` — CUTIEE's Computer Use library

This package is the agent layer of CUTIEE. It is intentionally
**Django-free**, **app-free**, and **persistence-agnostic** so it can
be vendored into other projects or used as a standalone library.

## What you get

| Symbol | Purpose |
|---|---|
| `ComputerUseRunner`, `buildComputerUseRunner` | Drive the screenshot ↔ function-call loop with auto-retry, approval gating, and screenshot persistence. |
| `GeminiComputerUseClient` | Live wrapper around `google.genai` with the `ComputerUse(environment="ENVIRONMENT_BROWSER")` tool. |
| `MockComputerUseClient` | Deterministic stand-in for tests / demo mode. Returns scripted actions. |
| `BrowserController`, `StubBrowserController`, `browserFromEnv` | Playwright wrapper with CDP-attach + per-domain storage_state support. |
| `ACEMemory`, `ACEPipeline`, `ReplayPlanner` | Self-evolving memory pipeline (`Reflector → QualityGate → Curator → Apply`) + procedural replay. |
| `BulletStore`, `InMemoryBulletStore` | Pluggable persistence interface. Swap in your own backend (e.g., Postgres, Neo4j, Redis). |
| `ApprovalGate`, `classifyRisk`, `buildAuditPayload` | Safety primitives. |

## Install

### Inside this repo

CUTIEE ships `agent/` as a sub-package of the top-level `cutiee` distribution:

```bash
git clone https://github.com/Edward-H26/CUTIEE.git
cd CUTIEE
uv sync                    # installs `cutiee` + `agent` together
uv run playwright install chromium
```

### Vendor `agent/` into your own project

Because `agent/` has zero coupling to Django or the rest of CUTIEE, you
can copy it directly into another codebase:

```bash
cp -r CUTIEE/agent /path/to/your/project/cutiee_agent
```

Then `from cutiee_agent import ComputerUseRunner` works unchanged.

### Pip install from git subdirectory

If you want the library without the rest of the Django app, add this to
your project's `pyproject.toml`:

```toml
dependencies = [
    "cutiee @ git+https://github.com/Edward-H26/CUTIEE.git",
]
```

`from agent import ComputerUseRunner` then resolves through the
installed `cutiee` package.

## Minimal standalone usage

```python
import asyncio
from agent import (
    ComputerUseRunner,
    GeminiComputerUseClient,
    BrowserController,
    ApprovalGate,
)

async def main() -> None:
    runner = ComputerUseRunner(
        browser = BrowserController(),                          # visible Chrome
        client = GeminiComputerUseClient(),                     # gemini-flash-latest
        approvalGate = ApprovalGate(),                          # auto-approves below MEDIUM
        initialUrl = "https://en.wikipedia.org",
        maxSteps = 10,
    )
    state = await runner.run(
        userId = "demo-user",
        taskId = "demo-task",
        taskDescription = "Find the 3 largest moons of Jupiter",
    )
    print(f"Completed: {state.isComplete} ({state.completionReason})")
    print(f"Steps: {state.stepCount()}, total cost: ${state.totalCostUsd:.4f}")

if __name__ == "__main__":
    asyncio.run(main())
```

That's the full surface — no Django, no Neo4j, no allauth, no ACE
memory. Just `pip install` the dependencies, set `GEMINI_API_KEY`,
and you have a working browser-driving agent.

## Adding memory + replay

If you want the self-evolving memory loop, plug in any
`BulletStore` implementation:

```python
from agent import (
    ACEMemory, ACEPipeline, ReplayPlanner,
    InMemoryBulletStore,
    buildComputerUseRunner,
)

memory = ACEMemory(userId = "demo", store = InMemoryBulletStore())
pipeline = ACEPipeline(memory = memory)
runner = buildComputerUseRunner(
    browser = BrowserController(),
    memory = pipeline,
    replayPlanner = ReplayPlanner(pipeline = pipeline),
    initialUrl = "https://en.wikipedia.org",
)
```

The runner now retrieves procedural templates before invoking the
model and writes lessons back at end of run.

## Required environment

| Variable | When | Default |
|---|---|---|
| `GEMINI_API_KEY` | Always (live `GeminiComputerUseClient`) | — |
| `CUTIEE_CU_MODEL` | Optional override | `gemini-flash-latest` |
| `CUTIEE_BROWSER_HEADLESS` | Optional | `false` (visible window) |
| `CUTIEE_BROWSER_CDP_URL` | Optional | unset (launches fresh chromium) |
| `CUTIEE_STORAGE_STATE_PATH` | Optional | unset (cold cookie jar) |
| `CUTIEE_CREDENTIAL_KEY` | Only if using `SemanticCredentialStore` | — (Fernet key) |

## Optional dependencies

The library is single-package but the deps it pulls in are scoped:

- `google-genai` — required for `GeminiComputerUseClient`
- `playwright` — required for `BrowserController` (real browser)
- `cryptography` — required only for `SemanticCredentialStore`
- `numpy` + `fastembed` — required only for `ACEMemory` (semantic embeddings)

If you only use `MockComputerUseClient` + `StubBrowserController`, you
can run with no optional deps installed.
