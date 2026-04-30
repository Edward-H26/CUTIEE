from __future__ import annotations

from neo4j.exceptions import ClientError

from agent.harness.state import AgentState
from apps.tasks import repo as tasksRepo
from apps.tasks.repo import TaskRow


def test_taskRowGetAbsoluteUrl() -> None:
    task = TaskRow({"id": "task-123"})
    assert task.get_absolute_url() == "/tasks/task-123/"


def test_createExecutionForIdleUserReturnsActiveAfterConstraintRace(monkeypatch) -> None:
    active = {"id": "exec-active", "task_id": "task-active", "status": "running"}
    calls = {"find": 0}

    def fakeFindActiveExecutionForUser(_userId: str):
        calls["find"] += 1
        return None if calls["find"] == 1 else active

    def fakeCreateExecution(**_kwargs):
        raise ClientError("active_execution_user")

    monkeypatch.setattr(tasksRepo, "findActiveExecutionForUser", fakeFindActiveExecutionForUser)
    monkeypatch.setattr(tasksRepo, "createExecution", fakeCreateExecution)

    execution, activeExecution = tasksRepo.createExecutionForIdleUser(
        userId="user-1",
        taskId="task-1",
        executionId="exec-new",
    )

    assert execution is None
    assert activeExecution == active


def test_persistAgentStateMarksTerminalFailureAsFailed(monkeypatch) -> None:
    finalized: dict[str, str] = {}
    updated: dict[str, str] = {}

    monkeypatch.setattr(
        tasksRepo,
        "getExecution",
        lambda _userId, _executionId: {"id": "exec-1"},
    )
    monkeypatch.setattr(tasksRepo, "appendStep", lambda **_kwargs: None)
    monkeypatch.setattr(tasksRepo, "finalizeExecution", lambda **kwargs: finalized.update(kwargs))
    monkeypatch.setattr(tasksRepo, "updateTaskStatus", lambda **kwargs: updated.update(kwargs))

    state = AgentState(taskId="task-1", userId="user-1", taskDescription="demo")
    state.executionId = "exec-1"
    state.markComplete("action_failed:fake fail")

    tasksRepo.persistAgentState(userId="user-1", taskId="task-1", state=state)

    assert finalized["status"] == "failed"
    assert updated["status"] == "failed"


def test_persistAgentStateMarksSuccessfulFinishAsCompleted(monkeypatch) -> None:
    finalized: dict[str, str] = {}
    updated: dict[str, str] = {}

    monkeypatch.setattr(
        tasksRepo,
        "getExecution",
        lambda _userId, _executionId: {"id": "exec-1"},
    )
    monkeypatch.setattr(tasksRepo, "appendStep", lambda **_kwargs: None)
    monkeypatch.setattr(tasksRepo, "finalizeExecution", lambda **kwargs: finalized.update(kwargs))
    monkeypatch.setattr(tasksRepo, "updateTaskStatus", lambda **kwargs: updated.update(kwargs))

    state = AgentState(taskId="task-1", userId="user-1", taskDescription="demo")
    state.executionId = "exec-1"
    state.markComplete("done")

    tasksRepo.persistAgentState(userId="user-1", taskId="task-1", state=state)

    assert finalized["status"] == "complete"
    assert updated["status"] == "completed"
