# cutiee-ace

**Self-evolving memory + procedural graph + bandit planner + state-verified replay for LLM agents.**

A standalone Python library extracted from [CUTIEE](https://github.com/Edward-H26/CUTIEE).
Brings the full miramemoria-parity ACE pipeline plus four phases built specifically
for browser-automation / Computer Use agents. Zero coupling to Django, allauth,
or any specific persistence layer.

---

## Install

```bash
# Minimum (heuristic Reflector, no LLM, no perceptual hash)
pip install cutiee-ace

# Recommended for browser agents
pip install "cutiee-ace[all]"
# pulls in: fastembed (semantic embeddings), cryptography (credential vault),
#           Pillow (state-verifier perceptual hash), google-genai (LLM Reflector)

# Or pick individual extras
pip install "cutiee-ace[gemini]"      # only LlmReflector + LlmActionDecomposer
pip install "cutiee-ace[verifier]"    # only StateVerifier perceptual hash
pip install "cutiee-ace[embeddings]"  # only fastembed for semantic retrieval
pip install "cutiee-ace[crypto]"      # only SemanticCredentialStore
```

---

## What you get (the four phases)

### Phase 1 — Self-evolving memory pipeline
The miramemoria classic. Three-strength bullets (`semantic` / `episodic` / `procedural`)
with per-channel exponential decay. The pipeline is `Reflector → QualityGate → Curator → Apply`:

```python
from cutiee_ace import (
    ACEMemory, ACEPipeline, InMemoryBulletStore, HeuristicReflector, LlmReflector,
)

memory = ACEMemory(userId="alice", store=InMemoryBulletStore())
memory.loadFromStore()
pipeline = ACEPipeline(memory=memory, reflector=HeuristicReflector())
# After your agent finishes a task:
result = pipeline.processExecution(my_agent_state)
print(f"accepted={result.accepted}, new_bullets={len(result.delta.new_bullets)}")
```

Switch to Gemini-driven reflection (richer lessons at the cost of one Gemini call per task):

```bash
export CUTIEE_REFLECTOR=llm
```

```python
from cutiee_ace import ACEPipeline, ACEMemory, buildReflector
pipeline = ACEPipeline.fromEnv(memory=memory)   # picks LlmReflector based on env
```

### Phase 2 — Procedural graph (`ActionNode` + `:NEXT`)

Store learned procedures as a chain of `ActionNode`s connected by `:NEXT` edges
instead of as flat bullets. Enables sub-graph matching for partial replay.

```python
from cutiee_ace import ActionNode, ProcedureGraph, InMemoryActionGraphStore

# After a successful run, persist the executed action sequence
nodes = [
    ActionNode(action_type="navigate", target="https://docs.google.com/spreadsheets",
               description="open sheet"),
    ActionNode(action_type="click_at", coord_x=384, coord_y=120,
               description="click column C header"),
    ActionNode(action_type="type_at", value="=SUM(A:B)",
               description="enter formula"),
]
graph = ProcedureGraph(
    procedure_id="p1", user_id="alice",
    task_description="make col C the sum of A and B",
    nodes=nodes,
)
store = InMemoryActionGraphStore()
store.saveGraph(graph)
```

LLM-driven decomposition (asks Gemini to break a task description into ActionNodes):

```python
from cutiee_ace import LlmActionDecomposer
decomposer = LlmActionDecomposer()        # needs GEMINI_API_KEY
graph = decomposer.decompose(
    userId="alice",
    taskDescription="make column C the average of A and B",
    initialUrl="https://docs.google.com/spreadsheets/d/abc",
)
print(f"decomposed into {len(graph.nodes)} steps")
```

### Phase 3 — Subgraph matching + bandit planner

Find which steps of the new task can be replayed from stored procedures:

```python
from cutiee_ace import SubgraphMatcher, findReusableSteps, reusableCoverageReport

matcher = SubgraphMatcher(minPrefixLength=2)
match = matcher.findBestMatch(newTask=newGraph, storedGraphs=store.loadGraphsForUser("alice"))
if match is not None:
    print(f"prefix replay: {match.matchedLength}/{match.newTaskTotalLength} nodes")

# Per-step lookup across ALL stored procedures (not just one prefix)
reusable = findReusableSteps(newTask=newGraph, storedGraphs=store.loadGraphsForUser("alice"))
report = reusableCoverageReport(reusable, len(newGraph.nodes))
print(f"safe replay coverage: {report['safe_replay_coverage'] * 100:.0f}%")
```

Epsilon-greedy + UCB bandit picks a per-task strategy:

```python
from cutiee_ace import Planner, CU_ACTIONS

planner = Planner(memory=memory, epsilon=0.1, ucbC=1.4)
strategy = planner.chooseAction(featureText=task_description, actions=CU_ACTIONS)
# ... run the agent with that strategy ...
planner.updateReward(strategy, reward=1.0 if state.isComplete else 0.2, confidence=0.8)
```

### Phase 4 — State verification

Before replaying a stored ActionNode, verify the page state matches what the
node expects (URL + perceptual hash). Avoids the "click the wrong thing because
the page is in a different state" failure mode:

```python
from cutiee_ace import StateVerifier, computeAverageHash

verifier = StateVerifier(phashThreshold=16)  # max bits of difference allowed
result = verifier.verify(
    node=stored_action_node,
    currentUrl="https://docs.google.com/spreadsheets/d/abc",
    currentScreenshot=current_png_bytes,
)
if result.safe:
    # Replay this node at zero cost
    ...
else:
    # Page state diverged; let the model pick instead
    print(f"unsafe to replay: {result.reason}")
```

When recording new ActionNodes, capture the state for future verification:

```python
node = ActionNode(
    action_type="type_at",
    value="=SUM(A:B)",
    coord_x=384, coord_y=140,
    expected_url="https://docs.google.com/spreadsheets/d/abc",
    expected_phash=computeAverageHash(post_action_screenshot_png_bytes),
)
```

---

## Plug your own persistence

Implement the `BulletStore` Protocol against any backend:

```python
from cutiee_ace import BulletStore, Bullet, DeltaUpdate

class PostgresBulletStore:
    def loadAll(self, userId: str) -> list[Bullet]: ...
    def upsertBullet(self, userId: str, bullet: Bullet) -> None: ...
    def updateBulletFields(self, userId: str, bulletId: str, patch: dict) -> None: ...
    def applyDelta(self, userId: str, delta: DeltaUpdate) -> None: ...

memory = ACEMemory(userId="alice", store=PostgresBulletStore())
```

Same for `ActionGraphStore`:

```python
from cutiee_ace import ActionGraphStore, ProcedureGraph

class MyGraphStore:
    def saveGraph(self, graph: ProcedureGraph) -> None: ...
    def loadGraphsForUser(self, userId: str, limit: int = 100) -> list[ProcedureGraph]: ...
    def loadGraphsByTopic(self, userId: str, topicSlug: str, limit: int = 10) -> list[ProcedureGraph]: ...
```

---

## Companion library: `cutiee-cu`

Pair with [`cutiee-cu`](../cutiee_cu/) (Computer Use runner for browser
automation) for the full self-evolving browser-agent stack:

```python
from cutiee_ace import ACEMemory, ACEPipeline, ReplayPlanner, InMemoryBulletStore
from cutiee_cu import ComputerUseRunner, GeminiComputerUseClient, BrowserController, ApprovalGate

memory = ACEMemory(userId="alice", store=InMemoryBulletStore())
pipeline = ACEPipeline(memory=memory)
runner = ComputerUseRunner(
    browser=BrowserController(),
    client=GeminiComputerUseClient(),
    approvalGate=ApprovalGate(),
    memory=pipeline,                                  # writes lessons after each run
    replayPlanner=ReplayPlanner(pipeline=pipeline),   # checks for known templates first
    initialUrl="https://docs.google.com/spreadsheets",
)
```

Cu also calls `cutiee_ace.StateVerifier` automatically when both packages are
installed (lazy import — cu degrades gracefully if cutiee-ace isn't available).

---

## Vendor-relocatable

```bash
cp -r CUTIEE/packages/cutiee_ace/cutiee_ace /path/to/your/project/my_memory
# Now `from my_memory import ACEPipeline, Planner, StateVerifier` works
```

All internal imports are relative (`from .X import Y`); the package is
rename-portable to any name without code changes.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `CUTIEE_REFLECTOR` | `heuristic` | `llm` switches `buildReflector()` to `LlmReflector` |
| `GEMINI_API_KEY` | — | Required for `LlmReflector` and `LlmActionDecomposer` |
| `ACE_REFLECTION_ENABLED` | `true` | `false` disables `LlmReflector` (falls back to heuristic) |
| `ACE_REFLECTION_MAX_TOKENS` | `700` | Max output tokens for the Gemini reflector call |
| `CUTIEE_CREDENTIAL_KEY` | — | Fernet key for `SemanticCredentialStore` |

## License

MIT. See repo root.
