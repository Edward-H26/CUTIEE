"""Cypher-backed CRUD for `:Task`, `:Execution`, `:Step` nodes.

Every function takes `userId` as its first argument so the cypher MATCH
pattern starts at `(:User {id: $userId})`. This enforces per-tenant scoping
at the query level and prevents accidental cross-user reads.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from agent.harness.state import AgentState, ObservationStep
from agent.persistence.neo4j_client import run_query, run_single


TaskRow = dict[str, Any]
ExecutionRow = dict[str, Any]


def _nowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


def createTask(
    userId: str,
    description: str,
    *,
    initialUrl: str = "",
    domainHint: str = "",
) -> TaskRow:
    taskId = str(uuid.uuid4())
    row = run_single(
        """
        MERGE (u:User {id: $user_id})
        CREATE (t:Task {
          id: $id,
          description: $description,
          initial_url: $initial_url,
          domain_hint: $domain_hint,
          status: $status,
          created_at: $created_at,
          updated_at: $created_at,
          run_count: 0,
          total_cost_usd: 0.0,
          last_execution_id: null
        })
        MERGE (u)-[:OWNS]->(t)
        RETURN t {.*} AS task
        """,
        user_id = str(userId),
        id = taskId,
        description = description,
        initial_url = initialUrl,
        domain_hint = domainHint,
        status = "pending",
        created_at = _nowIso(),
    )
    if row is None:
        raise RuntimeError(f"Failed to create task for user {userId!r}")
    return row["task"]


def getTask(userId: str, taskId: str) -> TaskRow | None:
    row = run_single(
        """
        MATCH (u:User {id: $user_id})-[:OWNS]->(t:Task {id: $task_id})
        RETURN t {.*} AS task
        """,
        user_id = str(userId),
        task_id = str(taskId),
    )
    return row["task"] if row else None


def listTasksForUser(userId: str, limit: int = 50) -> list[TaskRow]:
    rows = run_query(
        """
        MATCH (u:User {id: $user_id})-[:OWNS]->(t:Task)
        RETURN t {.*} AS task
        ORDER BY t.updated_at DESC
        LIMIT $limit
        """,
        user_id = str(userId),
        limit = int(limit),
    )
    return [row["task"] for row in rows]


def updateTaskStatus(
    userId: str,
    taskId: str,
    *,
    status: str,
    lastExecutionId: str | None = None,
    costDelta: float = 0.0,
) -> None:
    run_query(
        """
        MATCH (u:User {id: $user_id})-[:OWNS]->(t:Task {id: $task_id})
        SET t.status = $status,
            t.updated_at = $updated_at,
            t.last_execution_id = coalesce($last_execution_id, t.last_execution_id),
            t.total_cost_usd = coalesce(t.total_cost_usd, 0.0) + $cost_delta
        """,
        user_id = str(userId),
        task_id = str(taskId),
        status = status,
        updated_at = _nowIso(),
        last_execution_id = lastExecutionId,
        cost_delta = float(costDelta),
    )


def deleteTask(userId: str, taskId: str) -> None:
    run_query(
        """
        MATCH (u:User {id: $user_id})-[:OWNS]->(t:Task {id: $task_id})
        OPTIONAL MATCH (t)-[:EXECUTED_AS]->(e:Execution)
        OPTIONAL MATCH (e)-[:HAS_STEP]->(s:Step)
        DETACH DELETE t, e, s
        """,
        user_id = str(userId),
        task_id = str(taskId),
    )


def createExecution(
    userId: str,
    taskId: str,
    *,
    executionId: str | None = None,
    runIndex: int | None = None,
    replayed: bool = False,
    templateId: str | None = None,
) -> ExecutionRow:
    runIndex = runIndex if runIndex is not None else _nextRunIndex(userId, taskId)
    executionId = executionId or str(uuid.uuid4())
    row = run_single(
        """
        MATCH (u:User {id: $user_id})-[:OWNS]->(t:Task {id: $task_id})
        CREATE (e:Execution {
          id: $id,
          run_index: $run_index,
          status: 'running',
          started_at: $started_at,
          finished_at: null,
          step_count: 0,
          replayed: $replayed,
          template_id: $template_id,
          total_cost_usd: 0.0
        })
        MERGE (t)-[r:EXECUTED_AS {run_index: $run_index}]->(e)
        WITH e, t
        FOREACH (_ IN CASE WHEN $template_id IS NULL THEN [] ELSE [1] END |
            MERGE (tmpl:ProceduralTemplate {id: $template_id})
            MERGE (e)-[:REPLAYED_FROM]->(tmpl)
        )
        RETURN e {.*} AS execution
        """,
        user_id = str(userId),
        task_id = str(taskId),
        id = executionId,
        run_index = runIndex,
        started_at = _nowIso(),
        replayed = bool(replayed),
        template_id = templateId,
    )
    if row is None:
        raise RuntimeError(f"Failed to create execution for task {taskId!r}")
    return row["execution"]


def _nextRunIndex(userId: str, taskId: str) -> int:
    row = run_single(
        """
        MATCH (:User {id: $user_id})-[:OWNS]->(:Task {id: $task_id})-[:EXECUTED_AS]->(e:Execution)
        RETURN coalesce(max(e.run_index), -1) + 1 AS next_index
        """,
        user_id = str(userId),
        task_id = str(taskId),
    )
    return int(row["next_index"]) if row else 0


def appendStep(
    userId: str,
    executionId: str,
    step: ObservationStep,
) -> None:
    """Idempotent step write keyed on (executionId, index).

    Computer Use auto-retry can call appendStep twice with the same
    step.index; we MERGE on the natural key so the latest attempt
    overwrites the previous record instead of creating duplicate
    `:Step` nodes that inflate `e.step_count`. The cost/step counters
    on `:Execution` are recomputed in `finalizeExecution` from the
    actual step set, so we don't double-count cost on retry either.
    """
    if step.action is None:
        return
    run_query(
        """
        MATCH (:User {id: $user_id})-[:OWNS]->(:Task)-[:EXECUTED_AS]->(e:Execution {id: $execution_id})
        MERGE (s:Step {execution_id: $execution_id, index: $index})
        ON CREATE SET s.id = $id, s.created_at = $timestamp
        SET s.url = $url,
            s.dom_hash = $dom_hash,
            s.action_type = $action_type,
            s.target = $target,
            s.value = $value,
            s.reasoning = $reasoning,
            s.model = $model,
            s.tier = $tier,
            s.confidence = $confidence,
            s.risk = $risk,
            s.cost_usd = $cost_usd,
            s.verification_ok = $verification_ok,
            s.verification_note = $verification_note,
            s.duration_ms = $duration_ms,
            s.timestamp = $timestamp
        MERGE (e)-[:HAS_STEP {index: $index}]->(s)
        """,
        execution_id = str(executionId),
        user_id = str(userId),
        id = str(uuid.uuid4()),
        index = step.index,
        url = step.url,
        dom_hash = step.domHash,
        action_type = step.action.type.value,
        target = step.action.target,
        value = step.action.value or "",
        reasoning = step.action.reasoning or "",
        model = step.action.model_used or "",
        tier = step.action.tier,
        confidence = step.action.confidence,
        risk = step.action.risk.value,
        cost_usd = step.action.cost_usd,
        verification_ok = step.verificationOk,
        verification_note = step.verificationNote,
        duration_ms = step.durationMs,
        timestamp = step.timestamp.isoformat(),
    )


def finalizeExecution(
    userId: str,
    executionId: str,
    *,
    status: str,
    completionReason: str = "",
) -> None:
    """Recompute step_count and total_cost_usd from the actual step set.

    With idempotent appendStep (MERGE-based), retries no longer inflate
    the execution counters at write time. We do a single COUNT/SUM at
    finalization so the numbers reflect the final state, regardless of
    how many retries happened during the run.
    """
    run_query(
        """
        MATCH (:User {id: $user_id})-[:OWNS]->(:Task)-[:EXECUTED_AS]->(e:Execution {id: $execution_id})
        OPTIONAL MATCH (e)-[:HAS_STEP]->(s:Step)
        WITH e, count(s) AS step_count, coalesce(sum(s.cost_usd), 0.0) AS total_cost
        SET e.status = $status,
            e.finished_at = $finished_at,
            e.completion_reason = $completion_reason,
            e.step_count = step_count,
            e.total_cost_usd = total_cost
        """,
        user_id = str(userId),
        execution_id = str(executionId),
        status = status,
        finished_at = _nowIso(),
        completion_reason = completionReason,
    )


def getExecution(userId: str, executionId: str) -> ExecutionRow | None:
    row = run_single(
        """
        MATCH (:User {id: $user_id})-[:OWNS]->(:Task)-[:EXECUTED_AS]->(e:Execution {id: $execution_id})
        OPTIONAL MATCH (e)-[:HAS_STEP]->(s:Step)
        WITH e, count(s) AS step_count
        RETURN e {.*, step_count: step_count} AS execution
        """,
        user_id = str(userId),
        execution_id = str(executionId),
    )
    return row["execution"] if row else None


def listStepsForExecution(userId: str, executionId: str) -> list[dict[str, Any]]:
    rows = run_query(
        """
        MATCH (:User {id: $user_id})-[:OWNS]->(:Task)-[:EXECUTED_AS]->(:Execution {id: $execution_id})-[r:HAS_STEP]->(s:Step)
        RETURN s {.*} AS step
        ORDER BY r.index ASC
        """,
        user_id = str(userId),
        execution_id = str(executionId),
    )
    return [row["step"] for row in rows]


def listExecutionsForTask(userId: str, taskId: str) -> list[dict[str, Any]]:
    rows = run_query(
        """
        MATCH (:User {id: $user_id})-[:OWNS]->(:Task {id: $task_id})-[r:EXECUTED_AS]->(e:Execution)
        RETURN e {.*} AS execution
        ORDER BY r.run_index DESC
        """,
        user_id = str(userId),
        task_id = str(taskId),
    )
    return [row["execution"] for row in rows]


def persistAgentState(userId: str, taskId: str, state: AgentState) -> None:
    """Bulk-write all steps + finalize execution. Used by the services layer."""
    createExecution(
        userId = userId,
        taskId = taskId,
        executionId = state.executionId,
        replayed = state.replayed,
        templateId = state.templateId,
    )
    for step in state.history:
        appendStep(userId = userId, executionId = state.executionId, step = step)
    finalizeExecution(
        userId = userId,
        executionId = state.executionId,
        status = "complete" if state.isComplete else "incomplete",
        completionReason = state.completionReason,
    )
    updateTaskStatus(
        userId = userId,
        taskId = taskId,
        status = "completed" if state.isComplete else "failed",
        lastExecutionId = state.executionId,
        costDelta = state.totalCostUsd,
    )


def costSummaryForUser(userId: str) -> dict[str, Any]:
    # `replay_step_count` is the number of steps that ran inside an execution
    # marked `replayed = true`. We can't proxy on `s.cost_usd = 0` because the
    # mock VLM also reports zero cost on every step.
    row = run_single(
        """
        MATCH (u:User {id: $user_id})-[:OWNS]->(t:Task)-[:EXECUTED_AS]->(e:Execution)
        OPTIONAL MATCH (e)-[:HAS_STEP]->(s:Step)
        WITH t, e, count(s) AS step_count, coalesce(sum(s.cost_usd), 0.0) AS exec_cost
        RETURN coalesce(sum(exec_cost), 0.0) AS total_cost,
               count(DISTINCT t) AS task_count,
               count(DISTINCT e) AS execution_count,
               coalesce(sum(step_count), 0) AS step_count,
               coalesce(sum(CASE WHEN e.replayed THEN step_count ELSE 0 END), 0) AS replay_step_count
        """,
        user_id = str(userId),
    )
    if row is None:
        return {"total_cost": 0.0, "task_count": 0, "execution_count": 0, "step_count": 0, "replay_step_count": 0}
    return {
        "total_cost": float(row["total_cost"]),
        "task_count": int(row["task_count"]),
        "execution_count": int(row["execution_count"]),
        "step_count": int(row["step_count"]),
        "replay_step_count": int(row["replay_step_count"]),
    }


def costTimeseriesForUser(userId: str, days: int = 14) -> list[dict[str, Any]]:
    # Step.timestamp is stored as an ISO string, so cast it before any
    # datetime comparison; the original query silently returned zero rows
    # because string >= datetime evaluates to null.
    return run_query(
        """
        MATCH (u:User {id: $user_id})-[:OWNS]->(:Task)-[:EXECUTED_AS]->(e:Execution)-[:HAS_STEP]->(s:Step)
        WITH datetime(s.timestamp) AS ts, s.cost_usd AS cost
        WHERE ts >= datetime() - duration({days: $days})
        WITH date(ts) AS day, sum(cost) AS daily_cost, count(*) AS step_count
        RETURN toString(day) AS day, daily_cost, step_count
        ORDER BY day ASC
        """,
        user_id = str(userId),
        days = int(days),
    )


def tierDistributionForUser(userId: str) -> list[dict[str, Any]]:
    return run_query(
        """
        MATCH (:User {id: $user_id})-[:OWNS]->(:Task)-[:EXECUTED_AS]->(:Execution)-[:HAS_STEP]->(s:Step)
        RETURN s.tier AS tier, count(s) AS count, sum(s.cost_usd) AS cost_usd
        ORDER BY tier ASC
        """,
        user_id = str(userId),
    )


def asJsonExportRow(task: TaskRow, executions: list[ExecutionRow]) -> dict[str, Any]:
    """Used by the JSON export endpoint."""
    return {
        "task": task,
        "executions": json.loads(json.dumps(executions, default = str)),
    }
