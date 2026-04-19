# cutiee-cu

**Computer Use runner for LLM agents — Gemini ComputerUse tool + Playwright with optional state-verified mid-task replay.**

A standalone Python library extracted from [CUTIEE](https://github.com/Edward-H26/CUTIEE).
Drives a screenshot ↔ function-call loop against any model that supports
the Gemini `ComputerUse(environment="ENVIRONMENT_BROWSER")` tool, with
auto-retry, high-risk approval gating, screenshot persistence hooks, and
optional self-evolving memory + procedural replay (when paired with
[`cutiee-ace`](../cutiee_ace/)).

---

## Install

```bash
pip install cutiee-cu

# Required: install Chromium for Playwright
playwright install chromium

# Pair with the memory layer for self-evolving replay + state verification
pip install "cutiee-cu[ace]"
```

---

## Required environment

| Env var | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | Required for `GeminiComputerUseClient`. Get one at https://aistudio.google.com |
| `CUTIEE_CU_MODEL` | `gemini-flash-latest` | Override the CU model. Pin to `gemini-3-flash-preview` for deterministic replay |
| `CUTIEE_BROWSER_HEADLESS` | `false` | `true` for CI; default visible window |
| `CUTIEE_BROWSER_CDP_URL` | — | Attach to your real Chrome via `--remote-debugging-port=9222` |
| `CUTIEE_STORAGE_STATE_PATH` | — | Path to a Playwright `storage_state.json` for pre-authenticated runs |
| `CUTIEE_BROWSER_SLOW_MO_MS` | `0` | Inter-action delay (ms) for demo visibility |

---

## Quick start (standalone — no memory)

```python
import asyncio
from cutiee_cu import (
    ComputerUseRunner,
    GeminiComputerUseClient,
    BrowserController,
    ApprovalGate,
)

async def main():
    runner = ComputerUseRunner(
        browser=BrowserController(),         # visible window by default
        client=GeminiComputerUseClient(),    # gemini-flash-latest
        approvalGate=ApprovalGate(),         # auto-approves below MEDIUM risk
        initialUrl="https://en.wikipedia.org",
        maxSteps=10,
    )
    state = await runner.run(
        userId="demo",
        taskId="wiki",
        taskDescription="Find the four largest moons of Jupiter",
    )
    print(f"Completed: {state.isComplete}")
    print(f"Total cost: ${state.totalCostUsd:.4f}")
    for step in state.history:
        print(f"  step {step.index}: {step.action.type.value} (tier={step.action.tier})")

asyncio.run(main())
```

Output for a 5-step task: `~$0.0005-0.002 per task` at flash pricing, ~3 seconds per step.

---

## Tests / offline mode

`MockComputerUseClient` returns scripted actions — no API key needed:

```python
from cutiee_cu import (
    ComputerUseRunner, MockComputerUseClient, StubBrowserController, ApprovalGate,
    Action, ActionType,
)

runner = ComputerUseRunner(
    browser=StubBrowserController(),
    client=MockComputerUseClient(actionsToReturn=[
        Action(type=ActionType.CLICK_AT, coordinate=(100, 200)),
        Action(type=ActionType.FINISH, reasoning="done"),
    ]),
    approvalGate=ApprovalGate(),
)
# Runs without GEMINI_API_KEY or a real browser.
```

---

## With self-evolving memory (`pip install "cutiee-cu[ace]"`)

```python
from cutiee_ace import (
    ACEMemory, ACEPipeline, ReplayPlanner, InMemoryBulletStore,
    Planner, CU_ACTIONS,
)
from cutiee_cu import (
    ComputerUseRunner, GeminiComputerUseClient, BrowserController, ApprovalGate,
)

memory = ACEMemory(userId="alice", store=InMemoryBulletStore())
memory.loadFromStore()
pipeline = ACEPipeline(memory=memory)
planner = Planner(memory=memory)

# 1. Bandit picks a strategy
strategy = planner.chooseAction(featureText=task_description, actions=CU_ACTIONS)

# 2. Build the runner with memory + replay wired in
runner = ComputerUseRunner(
    browser=BrowserController(),
    client=GeminiComputerUseClient(),
    approvalGate=ApprovalGate(),
    memory=pipeline,                                  # writes lessons at end of run
    replayPlanner=ReplayPlanner(pipeline=pipeline),   # checks templates first
    initialUrl="https://docs.google.com/spreadsheets",
)
state = await runner.run(userId="alice", taskId="t1", taskDescription=task_description)

# 3. Reward the bandit
planner.updateReward(strategy, reward=1.0 if state.isComplete else 0.3, confidence=0.8)
```

When `cutiee_ace` is installed, the runner also automatically uses
`cutiee_ace.StateVerifier` to URL-check + perceptual-hash-check each
pre-matched node before replaying it. If the page state diverged from
what the stored node expected, replay halts and the model takes over.
**This is the key safety mechanism that makes mid-task replay viable.**

---

## Procedural graph + partial replay (Phase 2-4)

Pair with `cutiee-ace` to use stored `ProcedureGraph`s for partial replay:

```python
from cutiee_ace import (
    LlmActionDecomposer, SubgraphMatcher, InMemoryActionGraphStore,
)
from cutiee_cu import ComputerUseRunner

# 1. Decompose the new task via Gemini
decomposer = LlmActionDecomposer()
newGraph = decomposer.decompose(
    userId="alice",
    taskDescription="make column C the average of A and B",
    initialUrl="https://docs.google.com/spreadsheets/d/xyz",
)

# 2. Find the longest matching prefix from stored graphs
graphStore = InMemoryActionGraphStore()
matcher = SubgraphMatcher(minPrefixLength=2)
match = matcher.findBestMatch(newTask=newGraph, storedGraphs=graphStore.loadGraphsForUser("alice"))

# 3. Hand the matched prefix to the runner — it'll replay them at $0
#    then drive Gemini for the unmatched suffix
runner = ComputerUseRunner(
    browser=BrowserController(),
    client=GeminiComputerUseClient(),
    approvalGate=ApprovalGate(),
)
runner.prematchedNodes = match.matchedNodes if match else []

state = await runner.run(userId="alice", taskId="t1", taskDescription=task_description)
# state.history will show: tier=0 for replay-graph steps, tier=1 for Gemini steps
```

---

## Vendor-relocatable

```bash
cp -r CUTIEE/packages/cutiee_cu/cutiee_cu /path/to/your/project/my_runner
# Now `from my_runner import ComputerUseRunner, BrowserController` works
```

All internal imports are relative; package is rename-portable.

---

## Standalone vs paired with cutiee-ace

| Feature | cu standalone | cu + cutiee-ace |
|---|---|---|
| Real browser automation via Gemini CU | ✅ | ✅ |
| Mock client for tests | ✅ | ✅ |
| Approval gate for high-risk actions | ✅ | ✅ |
| Per-domain `storage_state.json` reuse | ✅ | ✅ |
| CDP attach to user's real Chrome | ✅ | ✅ |
| Self-evolving memory | ❌ | ✅ |
| Procedural-template replay | ❌ | ✅ |
| Subgraph-matching partial replay | ❌ | ✅ |
| State verification before replay | ❌ (no-op) | ✅ |
| Bandit-planned strategies | ❌ | ✅ |

The runner has a lazy import for `cutiee_ace.StateVerifier`, so cu works
fine standalone. Pair with cutiee-ace for the full self-evolving stack.

---

## License

MIT. See repo root.
