"""Server-rendered views for the tasks app."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.tasks import repo as tasksRepo
from apps.tasks.forms import TaskSubmissionForm


@login_required
def task_list(request: HttpRequest) -> HttpResponse:
    userId = str(request.user.pk)
    tasks = tasksRepo.listTasksForUser(userId, limit = 50)
    cost = tasksRepo.costSummaryForUser(userId)
    return render(
        request,
        "tasks/list.html",
        {"tasks": tasks, "cost": cost, "form": TaskSubmissionForm()},
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
    return render(
        request,
        "tasks/dashboard.html",
        {
            "cost": tasksRepo.costSummaryForUser(userId),
            "tier_distribution": tasksRepo.tierDistributionForUser(userId),
        },
    )
