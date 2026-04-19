"""Server-rendered views for the tasks app."""
from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from agent.persistence.healthcheck import checkNeo4jReachable
from apps.tasks import repo as tasksRepo
from apps.tasks.forms import TaskSubmissionForm

_logger = logging.getLogger("cutiee.tasks_views")


def _safeListAndCost(userId: str) -> tuple[list, dict, str]:
    """Best-effort fetch of tasks + cost. Returns (tasks, cost, db_health_msg).

    On Neo4j failure (auth, network, etc.), returns empty data + a
    user-facing health message instead of crashing the page. Lets the
    UI render with an actionable remediation hint.
    """
    try:
        tasks = tasksRepo.listTasksForUser(userId, limit = 50)
        cost = tasksRepo.costSummaryForUser(userId)
        return tasks, cost, ""
    except Exception:  # noqa: BLE001 - fail soft for UI
        _logger.warning("Neo4j fetch failed for /tasks/", exc_info = True)
        health = checkNeo4jReachable()
        msg = health.remediation or "Database temporarily unavailable."
        return [], {"total_cost": 0.0, "task_count": 0, "execution_count": 0,
                    "step_count": 0, "replay_step_count": 0}, msg


@login_required
def task_list(request: HttpRequest) -> HttpResponse:
    userId = str(request.user.pk)
    tasks, cost, dbError = _safeListAndCost(userId)
    return render(
        request,
        "tasks/list.html",
        {"tasks": tasks, "cost": cost, "form": TaskSubmissionForm(), "db_error": dbError},
    )


@login_required
def create_task(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return redirect("tasks:list")
    form = TaskSubmissionForm(request.POST)
    if not form.is_valid():
        userId = str(request.user.pk)
        tasks = tasksRepo.listTasksForUser(userId, limit = 50)
        cost = tasksRepo.costSummaryForUser(userId)
        return render(
            request,
            "tasks/list.html",
            {"tasks": tasks, "cost": cost, "form": form},
            status = 400,
        )

    description, initialUrl, domainHint = form.cleanedTuple()
    task = tasksRepo.createTask(
        userId = str(request.user.pk),
        description = description,
        initialUrl = initialUrl,
        domainHint = domainHint,
    )
    return redirect("tasks:detail", task_id = task["id"])


@login_required
def task_detail(request: HttpRequest, task_id: str) -> HttpResponse:
    userId = str(request.user.pk)
    task = tasksRepo.getTask(userId, str(task_id))
    if task is None:
        return redirect("tasks:list")
    executions = tasksRepo.listExecutionsForTask(userId, str(task_id))
    steps = []
    if executions:
        steps = tasksRepo.listStepsForExecution(userId, executions[0]["id"])
    return render(
        request,
        "tasks/detail.html",
        {"task": task, "executions": executions, "steps": steps},
    )


@login_required
def cost_dashboard(request: HttpRequest) -> HttpResponse:
    userId = str(request.user.pk)
    cost = {"total_cost": 0.0, "task_count": 0, "execution_count": 0,
            "step_count": 0, "replay_step_count": 0}
    tier_distribution: list = []
    db_error = ""
    try:
        cost = tasksRepo.costSummaryForUser(userId)
        tier_distribution = tasksRepo.tierDistributionForUser(userId)
    except Exception:  # noqa: BLE001 - fail soft for UI
        _logger.warning("Neo4j fetch failed for /tasks/dashboard/", exc_info = True)
        db_error = checkNeo4jReachable().remediation or "Database temporarily unavailable."
    return render(
        request,
        "tasks/dashboard.html",
        {"cost": cost, "tier_distribution": tier_distribution, "db_error": db_error},
    )
