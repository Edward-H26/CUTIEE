from __future__ import annotations

from apps.tasks.repo import TaskRow


def test_taskRowGetAbsoluteUrl() -> None:
    task = TaskRow({"id": "task-123"})
    assert task.get_absolute_url() == "/tasks/task-123/"
