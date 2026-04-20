"""Bridge between Django views and the Computer Use agent runner.

`runTaskForUser` is the function the API endpoint calls. CUTIEE runs every
task through `ComputerUseRunner` (screenshot + pixel coordinates via
gemini-flash-latest by default). The DOM-router stack was removed once
Gemini Flash gained the ComputerUse tool at flash pricing.

Wiring lives in `runner_factory.py`; this module owns the run-and-persist
sequence plus the live-progress publish path. The agent runs in a
background thread so Django's WSGI stack stays unaware of the asyncio
event loop the runner spawns.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from agent.harness.state import AgentState, ObservationStep
from apps.audit.screenshot_store import Neo4jScreenshotStore
from apps.memory_app.repo import upsertTemplate
from apps.tasks import progress_backend, repo as tasksRepo
from apps.tasks.runner_factory import buildLiveCuRunnerForUser, buildMockCuRunner

_SCREENSHOT_STORE: Neo4jScreenshotStore | None = None
_SCREENSHOT_STORE_LOCK = threading.Lock()
_logger = logging.getLogger("cutiee")


def _screenshotStore() -> Neo4jScreenshotStore:
    """Thread-safe lazy singleton for the Neo4j screenshot store.

    The agent runs in a background thread; the Django request thread
    also touches this for the screenshot-serving view. Without the lock,
    two simultaneous first-touches would race and instantiate two
    stores (and two driver pools).
    """
    global _SCREENSHOT_STORE
    if _SCREENSHOT_STORE is not None:
        return _SCREENSHOT_STORE
    with _SCREENSHOT_STORE_LOCK:
        if _SCREENSHOT_STORE is None:
            _SCREENSHOT_STORE = Neo4jScreenshotStore()
    return _SCREENSHOT_STORE


def persistScreenshot(executionId: str, stepIndex: int, pngBytes: bytes) -> None:
    try:
        _screenshotStore().save(executionId, stepIndex, pngBytes)
    except Exception:  # noqa: BLE001 - persistence is best-effort, run continues
        _logger.warning(
            "Failed to persist CU screenshot for %s step %s", executionId, stepIndex,
            exc_info = True,
        )


# Browser policy:
#
# Render's web tier ships without `playwright install chromium`, so the
# default for the demo deploy is the stub browser. Real-browser deploys
# (worker dynos with Playwright installed, or local laptops with chromium)
# must opt in by setting CUTIEE_USE_STUB_BROWSER=0.
USE_STUB_BROWSER = os.environ.get("CUTIEE_USE_STUB_BROWSER", "true").lower() not in {"0", "false", "no"}


@dataclass
class TaskRunSummary:
    taskId: str
    executionId: str
    stepCount: int
    totalCostUsd: float
    completed: bool
    completionReason: str
    replayed: bool
    tierUsage: dict[int, int]


def runTaskForUser(
    *,
    userId: str,
    taskId: str,
    description: str,
    initialUrl: str = "",
    useMockAgent: bool | None = None,
    executionId: str | None = None,
) -> TaskRunSummary:
    """Drive one task to completion through the Computer Use runner.

    Memory writeback (Reflector → Gate → Curator → Apply) runs in a
    background thread AFTER the task completes, so the user sees
    "complete" in the UI without waiting on Gemini reflection. Mirrors
    miramemoria's intent of decoupling the user's response time from
    the learning pipeline.

    `useMockAgent` forces the scripted `MockComputerUseClient` (used for
    tests and when `CUTIEE_ENV != "production"` for demo mode). When
    `None`, the agent mode is inferred from `CUTIEE_ENV`.
    """
    # Always store the user's prompt as a persistent event before the run
    # starts. Mirrors miramemoria's model of the request itself being a
    # memory artifact, not just the lessons extracted from it.
    _persistUserPrompt(userId = userId, taskId = taskId, description = description)

    state = asyncio.run(
        _runTaskAsync(
            userId = userId,
            taskId = taskId,
            description = description,
            initialUrl = initialUrl,
            useMockAgent = useMockAgent,
            executionId = executionId,
        )
    )

    # Template first, so the execution row can carry the templateId immediately.
    if state.replayed and state.templateId is None and state.history:
        state.templateId = upsertTemplate(
            userId = userId,
            description = description,
            domain = _domainFromUrl(initialUrl),
            embedding = None,
            actions = [step.action.asDict() if step.action else {} for step in state.history],
        )

    tasksRepo.persistAgentState(userId = userId, taskId = taskId, state = state)

    summary = _summarize(state)
    _publishProgress(state.executionId, summary, finished = True)

    # Background reflection: spawn a daemon thread so the response returns
    # immediately. The pipeline call can take seconds (Gemini Reflector +
    # Cypher writes), and there's no reason to hold the user's HTTP
    # response open for it. Failures log but don't surface.
    chosenStrategy = getattr(state, "_chosen_strategy", None)
    _scheduleBackgroundReflection(
        userId = userId, state = state, chosenStrategy = chosenStrategy,
    )

    return summary


def _persistUserPrompt(*, userId: str, taskId: str, description: str) -> None:
    """Record the user's prompt as a `:UserPrompt` Cypher node.

    Best-effort: failures log but don't block task execution.
    """
    try:
        from agent.persistence.neo4j_client import run_query
        run_query(
            """
            MERGE (u:User {id: $user_id})
            CREATE (p:UserPrompt {
                id: randomUUID(),
                task_id: $task_id,
                text: $text,
                created_at: datetime()
            })
            CREATE (u)-[:SUBMITTED]->(p)
            """,
            user_id = str(userId),
            task_id = str(taskId),
            text = description,
        )
    except Exception:  # noqa: BLE001 - best-effort persistence, never block
        _logger.debug("Failed to persist user prompt for task %s", taskId, exc_info = True)


def _scheduleBackgroundReflection(
    *, userId: str, state, chosenStrategy: str | None = None,
) -> None:
    """Run the ACE pipeline + record planner reward in a daemon thread."""
    if state.replayed:
        # Replays don't run the pipeline (the template already encodes
        # the lesson). Still record the reward so the planner learns.
        if chosenStrategy:
            _recordPlannerReward(userId, chosenStrategy, state)
        return

    def _worker():
        try:
            from agent.memory.ace_memory import ACEMemory
            from agent.memory.pipeline import ACEPipeline
            from apps.memory_app.store import Neo4jBulletStore
            memory = ACEMemory(userId = str(userId), store = Neo4jBulletStore())
            memory.loadFromStore()
            pipeline = ACEPipeline.fromEnv(memory = memory)
            pipeline.processExecution(state)
            if chosenStrategy:
                # Reward must be recorded against the SAME memory instance
                # so the planner_state mutation persists.
                from agent.memory.planner import Planner
                planner = Planner(memory = memory)
                planner.updateReward(
                    chosenStrategy,
                    reward = _computeReward(state),
                    confidence = 0.8,
                )
                # Persist planner state by writing the memory delta (no bullets,
                # but the upsert path will pick up plannerState)
                _persistPlannerState(userId = str(userId), plannerState = memory.plannerState)
        except Exception:  # noqa: BLE001
            _logger.warning(
                "Background ACE reflection failed for execution %s",
                state.executionId, exc_info = True,
            )

    threading.Thread(target = _worker, daemon = True, name = f"ace-reflect-{state.executionId[:8]}").start()


def _recordPlannerReward(userId: str, chosenStrategy: str, state) -> None:
    """Synchronous reward recording for the replay path (no full pipeline)."""
    try:
        from agent.memory.ace_memory import ACEMemory
        from agent.memory.planner import Planner
        from apps.memory_app.store import Neo4jBulletStore
        memory = ACEMemory(userId = str(userId), store = Neo4jBulletStore())
        memory.loadFromStore()
        planner = Planner(memory = memory)
        planner.updateReward(
            chosenStrategy, reward = _computeReward(state), confidence = 0.9,
        )
        _persistPlannerState(userId = str(userId), plannerState = memory.plannerState)
    except Exception:  # noqa: BLE001
        _logger.warning("Planner reward update failed", exc_info = True)


def _persistPlannerState(*, userId: str, plannerState: dict) -> None:
    """Write planner_state JSON to the user's :AceMemoryState node."""
    if not plannerState:
        return
    try:
        import json as _json
        from agent.persistence.neo4j_client import run_query
        run_query(
            """
            MERGE (u:User {id: $user_id})
            MERGE (u)-[:HAS_ACE_MEMORY]->(m:AceMemoryState)
            SET m.planner_state_json = $planner_state_json,
                m.updated_at = datetime()
            """,
            user_id = userId,
            planner_state_json = _json.dumps(plannerState),
        )
    except Exception:  # noqa: BLE001
        _logger.debug("Planner state persist failed", exc_info = True)


async def _runTaskAsync(
    *,
    userId: str,
    taskId: str,
    description: str,
    initialUrl: str,
    useMockAgent: bool | None,
    executionId: str | None = None,
) -> AgentState:
    cutieeEnv = os.environ.get("CUTIEE_ENV", "")
    # Allow local-mode operators to opt into the live Gemini ComputerUse
    # client via `CUTIEE_LOCAL_USE_GEMINI=true`. Useful for testing the
    # real CU pipeline against a Neo4j-backed local stack without flipping
    # the entire CUTIEE_ENV to production. Requires GEMINI_API_KEY.
    localUsesGemini = (
        cutieeEnv == "local"
        and os.environ.get("CUTIEE_LOCAL_USE_GEMINI", "false").lower() in {"1", "true", "yes"}
    )
    if useMockAgent is not None:
        forceMock = useMockAgent
    elif cutieeEnv == "production" or localUsesGemini:
        forceMock = False
    else:
        forceMock = True

    executionId = executionId or str(uuid.uuid4())

    if forceMock:
        runner = buildMockCuRunner(initialUrl = initialUrl)
        return await runner.run(
            userId = str(userId),
            taskId = taskId,
            taskDescription = description,
            executionId = executionId,
        )

    # === Production path: full miramemoria-parity orchestration ===
    # 1. Planner picks a CU strategy (single_shot / refine_with_replay / explore_2)
    # 2. If strategy supports replay AND we have stored procedures:
    #    a. Decompose the new task via Gemini (LlmActionDecomposer)
    #    b. Find longest matching prefix via SubgraphMatcher
    #    c. Pre-load matched nodes into the runner for zero-cost replay
    # 3. Run the runner; it executes pre-matched nodes then drives CU for the suffix
    # 4. After completion: persist the actual executed sequence as a new ProcedureGraph
    # 5. Update the planner's reward based on outcome

    state, strategy = await _runProductionTask(
        userId = str(userId),
        taskId = taskId,
        description = description,
        initialUrl = initialUrl,
        executionId = executionId,
    )
    state._chosen_strategy = strategy  # noqa: SLF001 - stash for post-run pipeline
    return state


async def _runProductionTask(
    *,
    userId: str,
    taskId: str,
    description: str,
    initialUrl: str,
    executionId: str,
) -> tuple[AgentState, str]:
    """Run a task through the full ACE-aware production pipeline.

    Returns the final AgentState plus the strategy the planner chose
    (so the caller can record reward against the right action).
    """
    from agent.memory.ace_memory import ACEMemory
    from agent.memory.action_graph import ActionNode, ProcedureGraph
    from agent.memory.decomposer import LlmActionDecomposer
    from agent.memory.planner import CU_ACTIONS, Planner
    from agent.memory.subgraph_match import SubgraphMatcher
    from apps.memory_app.action_graph_store import Neo4jActionGraphStore
    from apps.memory_app.store import Neo4jBulletStore

    # 1. Build memory + planner (planner state lives on ACEMemory)
    memory = ACEMemory(userId = userId, store = Neo4jBulletStore())
    memory.loadFromStore()
    planner = Planner(memory = memory)

    # 2. Strategy selection
    strategy = planner.chooseAction(featureText = description, actions = CU_ACTIONS)
    _logger.info("Planner picked strategy=%s for task=%s", strategy, taskId)

    # 3. Subgraph match (only for refine_with_replay; single_shot skips this)
    prematchedNodes: list[ActionNode] = []
    if strategy == "refine_with_replay":
        prematchedNodes = await _attemptSubgraphMatch(
            userId = userId,
            description = description,
            initialUrl = initialUrl,
            graphStore = Neo4jActionGraphStore(),
            decomposer = LlmActionDecomposer(),
            matcher = SubgraphMatcher(minPrefixLength = 2),
        )

    # 4. Build the runner and run it
    runner = buildLiveCuRunnerForUser(
        userId = userId,
        initialUrl = initialUrl,
        executionId = executionId,
        onProgress = _progressCallback,
        screenshotSink = persistScreenshot,
        useStubBrowser = USE_STUB_BROWSER,
    )
    runner.prematchedNodes = prematchedNodes  # consumed at runner.run() start

    state = await runner.run(
        userId = userId,
        taskId = taskId,
        taskDescription = description,
        executionId = executionId,
    )

    # 5. Persist the actual executed sequence as a new ProcedureGraph
    if state.isComplete and not state.replayed and state.history:
        try:
            _persistProcedureGraph(
                userId = userId,
                description = description,
                state = state,
                graphStore = Neo4jActionGraphStore(),
            )
        except Exception:  # noqa: BLE001
            _logger.warning("Failed to persist procedure graph", exc_info = True)

    return state, strategy


async def _attemptSubgraphMatch(
    *,
    userId: str,
    description: str,
    initialUrl: str,
    graphStore,
    decomposer,
    matcher,
) -> list:
    """Try to find a stored procedure that prefix-matches the new task.

    Also computes per-step reusable-step coverage across ALL stored
    procedures (telemetry only — execution still uses the safe prefix
    match for state-coherence reasons; see findReusableSteps docstring).

    Returns the matched ActionNodes from the prefix match, or empty
    list if no match meets the minimum prefix length.
    """
    try:
        storedGraphs = graphStore.loadGraphsForUser(userId, limit = 20)
    except Exception:  # noqa: BLE001
        _logger.debug("loadGraphsForUser failed; no replay candidates", exc_info = True)
        return []
    if not storedGraphs:
        return []

    newGraph = decomposer.decompose(
        userId = userId,
        taskDescription = description,
        initialUrl = initialUrl,
    )
    if not newGraph.nodes:
        return []

    # Telemetry: per-step reuse across ALL stored graphs (not just one prefix)
    from agent.memory.subgraph_match import findReusableSteps, reusableCoverageReport
    reusable = findReusableSteps(newTask = newGraph, storedGraphs = storedGraphs)
    coverage = reusableCoverageReport(reusable, len(newGraph.nodes))
    if coverage["matched"] > 0:
        _logger.info(
            "Per-step reuse coverage: %d/%d matched (%d safe-to-replay), %.0f%% safe coverage",
            coverage["matched"], coverage["total_steps"],
            coverage["safe_to_replay"], coverage["safe_replay_coverage"] * 100,
        )

    # Execution: only the contiguous prefix match (option a — safe semantics)
    match = matcher.findBestMatch(newTask = newGraph, storedGraphs = storedGraphs)
    if match is None:
        return []
    _logger.info(
        "Subgraph prefix match: %d/%d nodes (%.0f%% replayable) from procedure %s",
        match.matchedLength, match.newTaskTotalLength,
        match.coverageRatio * 100, match.storedProcedureId[:8],
    )
    return match.matchedNodes


def _persistProcedureGraph(*, userId: str, description: str, state, graphStore) -> None:
    """Convert successful AgentState.history → ProcedureGraph → Neo4j.

    Uses the ACTUAL executed actions (not the LLM's pre-run decomposition)
    so the stored graph reflects ground truth, not the decomposer's guess.

    Records `expected_url` + `expected_phash` per node from the post-action
    screenshot so the StateVerifier can later check whether replay is safe.
    The phash is fetched from the Neo4j screenshot store keyed on
    (executionId, stepIndex). If unavailable, the node is saved without
    a phash and verification skips that signal.
    """
    from agent.memory.action_graph import ActionEdge, ActionNode, ProcedureGraph
    from agent.memory.state_verifier import computeAverageHash
    from apps.audit.screenshot_store import Neo4jScreenshotStore
    import uuid as _uuid

    screenshotStore = Neo4jScreenshotStore()

    nodes: list[ActionNode] = []
    for step in state.history:
        if step.action is None:
            continue
        coord = step.action.coordinate
        # Best-effort fetch the post-action screenshot to compute phash.
        # Misses (no PNG stored, sweep removed it, fetch error) are tolerated.
        expectedPhash = ""
        try:
            png = screenshotStore.fetch(state.executionId, step.index)
            if png:
                expectedPhash = computeAverageHash(png)
        except Exception:  # noqa: BLE001
            pass
        nodes.append(ActionNode(
            action_type = step.action.type.value,
            target = step.action.target or "",
            value = step.action.value or "",
            coord_x = coord[0] if coord else None,
            coord_y = coord[1] if coord else None,
            description = step.action.reasoning or "",
            expected_url = step.url or "",
            expected_phash = expectedPhash,
        ))

    if len(nodes) < 2:
        return  # not worth storing single-step procedures

    procedureId = str(_uuid.uuid4())
    edges = [
        ActionEdge(
            source_id = nodes[i].id,
            target_id = nodes[i + 1].id,
            procedure_id = procedureId,
            sequence_index = i,
        )
        for i in range(len(nodes) - 1)
    ]
    graph = ProcedureGraph(
        procedure_id = procedureId,
        user_id = userId,
        task_description = description,
        nodes = nodes,
        edges = edges,
        metadata = {"topic_slug": _slugify(description)},
    )
    graphStore.saveGraph(graph)
    _logger.info("Persisted procedure graph %s with %d nodes", procedureId[:8], len(nodes))


def _slugify(text: str) -> str:
    import re as _re
    if not text:
        return "task"
    normalized = _re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    return normalized.strip("-")[:48] or "task"


def _computeReward(state: AgentState) -> float:
    """Map the AgentState outcome to a [0,1] reward for the bandit."""
    if not state.isComplete:
        return 0.0
    reason = state.completionReason or ""
    if reason.startswith("action_failed") or reason.startswith("rejected"):
        return 0.3
    if reason.startswith("auth_expired"):
        return 0.1
    if reason in ("max_steps_reached",):
        return 0.2
    # All other completions (finish_action, replay_success, demo_complete...)
    return 1.0


def _progressCallback(state: AgentState, step: ObservationStep) -> None:
    """Per-step hook: publish to the in-process progress cache AND
    persist the step to Neo4j so the detail page's steps table updates
    in real time. Best-effort — Neo4j hiccups never abort the run."""
    _publishProgress(state.executionId, _summarize(state, latestStep = step), finished = False)
    try:
        tasksRepo.appendStep(
            userId = state.userId,
            executionId = state.executionId,
            step = step,
        )
    except Exception:  # noqa: BLE001 - never block the agent on a write hiccup
        _logger.debug(
            "Live appendStep failed for execution=%s step=%s",
            state.executionId, step.index, exc_info = True,
        )


def _publishProgress(executionId: str, summary: TaskRunSummary, *, finished: bool) -> None:
    payload = {
        "executionId": summary.executionId,
        "stepCount": summary.stepCount,
        "totalCostUsd": summary.totalCostUsd,
        "completed": finished and summary.completed,
        "completionReason": summary.completionReason,
        "replayed": summary.replayed,
        "tierUsage": summary.tierUsage,
        "finished": finished,
    }
    progress_backend.publishProgress(executionId, payload)


def fetchProgress(executionId: str) -> dict[str, Any] | None:
    return progress_backend.fetchProgress(executionId)


def _summarize(state: AgentState, *, latestStep: ObservationStep | None = None) -> TaskRunSummary:
    tierUsage: dict[int, int] = {}
    for step in state.history:
        if step.action is None:
            continue
        tierUsage[step.action.tier] = tierUsage.get(step.action.tier, 0) + 1
    if latestStep is not None and latestStep.action is not None:
        tierUsage.setdefault(latestStep.action.tier, 0)

    return TaskRunSummary(
        taskId = state.taskId,
        executionId = state.executionId,
        stepCount = state.stepCount(),
        totalCostUsd = round(state.totalCostUsd, 6),
        completed = state.isComplete,
        completionReason = state.completionReason,
        replayed = state.replayed,
        tierUsage = tierUsage,
    )


def _domainFromUrl(url: str) -> str:
    if not url or "://" not in url:
        return ""
    rest = url.split("://", 1)[1]
    return rest.split("/", 1)[0]
