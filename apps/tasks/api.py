"""JSON + HTMX endpoints for the tasks app.

The agent runs synchronously inside `runTaskForUser`, but the UI uses HTMX
polling so the user sees per-step updates. The progress cache lives in
`apps.tasks.services._PROGRESS_CACHE` (process-local). Production deploys
should swap that for Redis once horizontal scaling is needed; for INFO490
the single-worker Render instance is fine.
"""
from __future__ import annotations

import json
import os
import threading

import httpx
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.audit.repo import auditCountForUser, listAuditForUser
from apps.memory_app.repo import (
    listBulletsForUser,
    listTemplatesForUser,
    memoryDashboardStats,
)
from apps.tasks import repo as tasksRepo
from apps.tasks.services import fetchProgress, runTaskForUser


@require_POST
@login_required
def run_task_view(request: HttpRequest, task_id: str) -> JsonResponse:
    task = tasksRepo.getTask(str(request.user.pk), str(task_id))
    if task is None:
        return JsonResponse({"error": "task not found"}, status = 404)

    useMockRaw = request.POST.get("use_mock") or request.GET.get("use_mock")
    useMock = None
    if useMockRaw is not None:
        useMock = str(useMockRaw).lower() in {"1", "true", "yes"}

    threading.Thread(
        target = _runInBackground,
        kwargs = {
            "userId": str(request.user.pk),
            "taskId": task["id"],
            "description": task["description"],
            "initialUrl": task.get("initial_url") or "",
            "useMockAgent": useMock,
        },
        daemon = True,
    ).start()
    return JsonResponse({"status": "started", "task_id": task["id"]})


def _runInBackground(**kwargs: object) -> None:
    try:
        runTaskForUser(**kwargs)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - background thread, surface in audit instead
        pass


@require_GET
@login_required
def task_status(request: HttpRequest, execution_id: str) -> JsonResponse:
    snapshot = fetchProgress(str(execution_id))
    if snapshot is None:
        execution = tasksRepo.getExecution(str(request.user.pk), str(execution_id))
        if execution is None:
            return JsonResponse({"status": "unknown"}, status = 404)
        return JsonResponse({
            "executionId": execution["id"],
            "stepCount": execution.get("step_count", 0),
            "totalCostUsd": execution.get("total_cost_usd", 0.0),
            "completed": execution.get("status") == "complete",
            "completionReason": execution.get("completion_reason", ""),
            "replayed": execution.get("replayed", False),
            "tierUsage": {},
            "finished": True,
        })
    return JsonResponse(snapshot)


@require_GET
@login_required
def cost_summary(request: HttpRequest) -> JsonResponse:
    return JsonResponse(tasksRepo.costSummaryForUser(str(request.user.pk)))


@require_GET
@login_required
def cost_timeseries(request: HttpRequest) -> JsonResponse:
    days = int(request.GET.get("days", "14") or "14")
    rows = tasksRepo.costTimeseriesForUser(str(request.user.pk), days = days)
    return JsonResponse({"series": rows})


@require_GET
@login_required
def tier_distribution(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"distribution": tasksRepo.tierDistributionForUser(str(request.user.pk))})


@require_GET
@login_required
def memory_stats(request: HttpRequest) -> JsonResponse:
    stats = memoryDashboardStats(str(request.user.pk))
    stats["bullets"] = listBulletsForUser(str(request.user.pk))[:5]
    return JsonResponse(stats)


@require_GET
@login_required
def memory_export(request: HttpRequest) -> HttpResponse:
    payload = {
        "templates": listTemplatesForUser(str(request.user.pk)),
        "bullets": listBulletsForUser(str(request.user.pk)),
    }
    response = HttpResponse(
        json.dumps(payload, default = str, indent = 2),
        content_type = "application/json",
    )
    response["Content-Disposition"] = 'attachment; filename="cutiee-memory-export.json"'
    return response


@require_GET
@login_required
def audit_feed(request: HttpRequest) -> JsonResponse:
    limit = min(int(request.GET.get("limit", "50") or "50"), 200)
    offset = int(request.GET.get("offset", "0") or "0")
    return JsonResponse({
        "entries": listAuditForUser(str(request.user.pk), limit = limit, offset = offset),
        "total": auditCountForUser(str(request.user.pk)),
    })


@require_GET
def vlm_health(request: HttpRequest) -> HttpResponse:
    env = os.environ.get("CUTIEE_ENV", "")
    isHtmx = request.headers.get("HX-Request") == "true"

    if env == "production":
        ready = bool(os.environ.get("GEMINI_API_KEY"))
        payload = {
            "status": "ready" if ready else "loading",
            "env": "production",
            "model": os.environ.get("GEMINI_MODEL_TIER2", "gemini-3.1-flash"),
        }
    elif env == "local":
        url = os.environ.get("QWEN_SERVER_URL", "http://localhost:8001")
        try:
            with httpx.Client(timeout = 1.0) as client:
                resp = client.get(f"{url}/health")
            status = "ready" if resp.status_code == 200 else "loading"
        except (httpx.ConnectError, httpx.TimeoutException):
            status = "loading"
        payload = {"status": status, "env": "local", "model": "qwen3.5-0.8b"}
    else:
        payload = {"status": "unavailable", "env": env or "unknown", "model": "n/a"}

    if not isHtmx:
        return JsonResponse(payload)

    if payload["status"] == "ready":
        return HttpResponse(
            f"<div id='vlm-status-banner' data-status='ready' data-model='{payload['model']}'></div>"
        )
    label = "Connecting to Gemini" if payload["env"] == "production" else "Warming up Qwen3.5 0.8B"
    return HttpResponse(
        f"""
        <div id='vlm-status-banner' class='vlm-banner vlm-banner--{payload['status']}'
             hx-get='{request.path}' hx-trigger='every 2s' hx-swap='outerHTML' hx-target='this'>
          <span class='dot'></span> {label} ({payload['status']})
        </div>
        """
    )


@csrf_exempt
@require_http_methods(["POST"])
@login_required
def delete_task(request: HttpRequest, task_id: str) -> JsonResponse:
    tasksRepo.deleteTask(str(request.user.pk), str(task_id))
    return JsonResponse({"status": "deleted", "task_id": str(task_id)})


@require_GET
@login_required
def task_detail_json(request: HttpRequest, task_id: str) -> JsonResponse:
    task = get_object_or_404_helper(str(request.user.pk), str(task_id))
    executions = tasksRepo.listExecutionsForTask(str(request.user.pk), str(task_id))
    steps = []
    if executions:
        steps = tasksRepo.listStepsForExecution(str(request.user.pk), executions[0]["id"])
    return JsonResponse({"task": task, "executions": executions, "steps": steps})


def get_object_or_404_helper(userId: str, taskId: str) -> dict:
    task = tasksRepo.getTask(userId, taskId)
    if task is None:
        from django.http import Http404

        raise Http404("task not found")
    return task
