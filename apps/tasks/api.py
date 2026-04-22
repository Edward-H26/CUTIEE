"""JSON + HTMX endpoints for the tasks app.

The agent runs synchronously inside `runTaskForUser`, but the UI uses HTMX
polling so the user sees per-step updates. The progress cache lives in
`apps.tasks.services._PROGRESS_CACHE` (process-local). Production deploys
should swap that for Redis once horizontal scaling is needed; for INFO490
the single-worker Render instance is fine.
"""
from __future__ import annotations

import json
import logging
import os
import threading

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.audit.repo import auditCountForUser, listAuditForUser
from apps.common.query_utils import safeInt
from apps.memory_app.repo import (
    listBulletsForUser,
    listTemplatesForUser,
    memoryDashboardStats,
)
from apps.tasks import repo as tasksRepo
from apps.tasks.approval_queue import (
    pendingApprovalFor,
    submitDecision,
)
from apps.tasks.partials import renderApprovalModal, renderPreviewModal, renderStatusPartial
from apps.tasks.preview_queue import fetchPreviewApproval, setPreviewStatus
from apps.tasks.services import _screenshotStore, fetchProgress, runTaskForUser

logger = logging.getLogger("cutiee")


@require_POST
@login_required
def run_task_view(request: HttpRequest, task_id: str) -> JsonResponse:
    task = tasksRepo.getTask(str(request.user.pk), str(task_id))
    if task is None:
        return JsonResponse({"error": "task not found"}, status = 404)

    # Reject duplicate clicks: if the latest execution is still running,
    # short-circuit instead of spawning a parallel thread that would race
    # against the same procedural-graph write.
    existing = tasksRepo.listExecutionsForTask(str(request.user.pk), str(task_id))
    if existing and existing[0].get("status") == "running":
        return JsonResponse({
            "status": "already_running",
            "task_id": task["id"],
            "execution_id": existing[0]["id"],
        }, status = 409)

    useMockRaw = request.POST.get("use_mock") or request.GET.get("use_mock")
    useMock = None
    if useMockRaw is not None:
        useMock = str(useMockRaw).lower() in {"1", "true", "yes"}

    # Create the execution row synchronously BEFORE spawning the thread so
    # the detail page sees an in-flight execution on the next render. The
    # row starts with status='running' and step_count=0; the agent loop
    # writes each step into Neo4j live via _publishProgress hooks.
    import uuid as _uuid
    executionId = str(_uuid.uuid4())
    tasksRepo.createExecution(
        userId = str(request.user.pk),
        taskId = task["id"],
        executionId = executionId,
    )

    threading.Thread(
        target = _runInBackground,
        kwargs = {
            "userId": str(request.user.pk),
            "taskId": task["id"],
            "description": task["description"],
            "initialUrl": task.get("initial_url") or "",
            "useMockAgent": useMock,
            "executionId": executionId,
        },
        daemon = True,
    ).start()
    return JsonResponse({"status": "started", "task_id": task["id"], "execution_id": executionId})


def _runInBackground(**kwargs: object) -> None:
    try:
        runTaskForUser(**kwargs)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 - background thread, log and surface
        logger.exception("Background task run failed: %s", exc)


@require_GET
@login_required
def task_status(request: HttpRequest, execution_id: str):
    snapshot = fetchProgress(str(execution_id))
    if snapshot is None:
        execution = tasksRepo.getExecution(str(request.user.pk), str(execution_id))
        if execution is None:
            if request.headers.get("HX-Request") == "true":
                return HttpResponse("<span class='cutiee-text-sm cutiee-muted'>Execution not found.</span>", status = 404)
            return JsonResponse({"status": "unknown"}, status = 404)
        snapshot = {
            "executionId": execution["id"],
            "stepCount": execution.get("step_count", 0),
            "totalCostUsd": execution.get("total_cost_usd", 0.0),
            "completed": execution.get("status") == "complete",
            "completionReason": execution.get("completion_reason", ""),
            "replayed": execution.get("replayed", False),
            "tierUsage": {},
            "finished": True,
        }
    if request.headers.get("HX-Request") == "true":
        snapshot = dict(snapshot)
        snapshot["_pollUrl"] = request.path
        return renderStatusPartial(snapshot)
    return JsonResponse(snapshot)


_DEFAULT_COST = {"total_cost": 0.0, "task_count": 0, "execution_count": 0,
                 "step_count": 0, "replay_step_count": 0}
_DEFAULT_MEMORY = {"bullet_count": 0, "template_count": 0,
                   "stale_template_count": 0, "avg_strength": 0.0}


def _safeJson(builder, fallback):
    """Run a Cypher-backed builder and degrade to fallback on Neo4j errors."""
    try:
        return JsonResponse(builder())
    except Exception:  # noqa: BLE001 - fail soft for UI-facing JSON
        logger.warning("Neo4j fetch failed for JSON endpoint", exc_info = True)
        payload = dict(fallback)
        payload["db_error"] = "Database temporarily unavailable."
        return JsonResponse(payload)


@require_GET
@login_required
def cost_summary(request: HttpRequest) -> JsonResponse:
    userId = str(request.user.pk)
    return _safeJson(lambda: tasksRepo.costSummaryForUser(userId), _DEFAULT_COST)


@require_GET
@login_required
def cost_timeseries(request: HttpRequest) -> JsonResponse:
    days = safeInt(request.GET.get("days"), default = 14, minimum = 1, maximum = 365)
    userId = str(request.user.pk)
    return _safeJson(
        lambda: {"series": tasksRepo.costTimeseriesForUser(userId, days = days)},
        {"series": []},
    )


@require_GET
@login_required
def tier_distribution(request: HttpRequest) -> JsonResponse:
    userId = str(request.user.pk)
    return _safeJson(
        lambda: {"distribution": tasksRepo.tierDistributionForUser(userId)},
        {"distribution": []},
    )


@require_GET
@login_required
def memory_stats(request: HttpRequest) -> JsonResponse:
    userId = str(request.user.pk)

    def build():
        stats = memoryDashboardStats(userId)
        stats["bullets"] = listBulletsForUser(userId)[:5]
        return stats

    fallback = dict(_DEFAULT_MEMORY)
    fallback["bullets"] = []
    return _safeJson(build, fallback)


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
    limit = safeInt(request.GET.get("limit"), default = 50, minimum = 1, maximum = 200)
    offset = safeInt(request.GET.get("offset"), default = 0, minimum = 0)
    userId = str(request.user.pk)
    return _safeJson(
        lambda: {
            "entries": listAuditForUser(userId, limit = limit, offset = offset),
            "total": auditCountForUser(userId),
        },
        {"entries": [], "total": 0},
    )


@require_GET
def vlm_health(request: HttpRequest) -> HttpResponse:
    """Status banner for the Computer Use model.

    Production reports Gemini readiness based on `GEMINI_API_KEY`.
    Local mode uses `MockComputerUseClient` (post-pivot — no Qwen server),
    so the banner is always "ready" with the mock model.
    """
    env = os.environ.get("CUTIEE_ENV", "")
    isHtmx = request.headers.get("HX-Request") == "true"

    if env == "production":
        ready = bool(os.environ.get("GEMINI_API_KEY"))
        payload = {
            "status": "ready" if ready else "loading",
            "env": "production",
            "model": os.environ.get("CUTIEE_CU_MODEL", "gemini-flash-latest"),
        }
    elif env == "local":
        payload = {"status": "ready", "env": "local", "model": "mock-cu-client"}
    else:
        payload = {"status": "unavailable", "env": env or "unknown", "model": "n/a"}

    if not isHtmx:
        return JsonResponse(payload)

    if payload["status"] == "ready":
        return HttpResponse(format_html(
            "<div id='vlm-status-banner' data-status='ready' data-model='{model}'></div>",
            model = payload["model"],
        ))
    label = (
        "Connecting to Gemini"
        if payload["env"] == "production"
        else f"Loading {payload['model']}"
    )
    return HttpResponse(format_html(
        "<div id='vlm-status-banner' class='vlm-banner vlm-banner--{status}'"
        " hx-get='{path}' hx-trigger='every 2s' hx-swap='outerHTML' hx-target='this'>"
        "<span class='dot'></span> {label} ({status})"
        "</div>",
        status = payload["status"],
        path = request.path,
        label = label,
    ))


@require_http_methods(["POST"])
@login_required
def delete_task(request: HttpRequest, task_id: str) -> JsonResponse:
    tasksRepo.deleteTask(str(request.user.pk), str(task_id))
    return JsonResponse({"status": "deleted", "task_id": str(task_id)})


@require_GET
@login_required
def approval_pending(request: HttpRequest, execution_id: str) -> HttpResponse:
    """HTMX poll endpoint that returns the modal HTML when an approval is waiting."""
    userId = str(request.user.pk)
    if tasksRepo.getExecution(userId, str(execution_id)) is None:
        return HttpResponse(status = 404)
    pending = pendingApprovalFor(str(execution_id))
    return renderApprovalModal(str(execution_id), pending)


@require_POST
@login_required
def approval_decide(request: HttpRequest, execution_id: str, decision: str) -> JsonResponse:
    userId = str(request.user.pk)
    if tasksRepo.getExecution(userId, str(execution_id)) is None:
        return JsonResponse({"error": "execution not found"}, status = 404)
    approved = decision.lower() in {"approve", "approved", "yes", "ok"}
    delivered = submitDecision(str(execution_id), approved)
    return JsonResponse({"delivered": delivered, "approved": approved})


@require_GET
@login_required
def preview_pending(request: HttpRequest, execution_id: str) -> HttpResponse:
    """HTMX poll endpoint for the pre-run preview modal.

    Auth: must own the execution. Returns the approve/cancel modal when
    the :PreviewApproval node is in 'pending' state, otherwise an empty
    slot that keeps polling so the UI reacts to a late-arriving preview.
    """
    userId = str(request.user.pk)
    if tasksRepo.getExecution(userId, str(execution_id)) is None:
        return HttpResponse(status = 404)
    preview = fetchPreviewApproval(str(execution_id))
    return renderPreviewModal(str(execution_id), preview)


@require_POST
@login_required
def preview_decide(request: HttpRequest, execution_id: str, decision: str) -> JsonResponse:
    """Flip the preview's status to approved or cancelled.

    The agent's `runPreviewAndWait` is polling the same :PreviewApproval
    node in Neo4j and sees the flip on its next poll tick, which
    releases the runner to start (approved) or exit cleanly (cancelled)
    without touching the browser.
    """
    userId = str(request.user.pk)
    if tasksRepo.getExecution(userId, str(execution_id)) is None:
        return JsonResponse({"error": "execution not found"}, status = 404)
    approved = decision.lower() in {"approve", "approved", "yes", "ok"}
    status = "approved" if approved else "cancelled"
    delivered = setPreviewStatus(str(execution_id), status = status)
    return JsonResponse({"delivered": delivered, "status": status})


@require_GET
@login_required
def step_screenshot(request: HttpRequest, execution_id: str, step_index: int) -> HttpResponse:
    """Serve a single per-step PNG from the Neo4j screenshot store.

    Auth: must own the execution. Cached for 1 hour because step images
    never change after capture (TTL cleanup at the store level handles
    eventual deletion).
    """
    userId = str(request.user.pk)
    execution = tasksRepo.getExecution(userId, str(execution_id))
    if execution is None:
        return HttpResponse(status = 404)
    png = _screenshotStore().fetch(str(execution_id), int(step_index))
    if png is None:
        return HttpResponse(status = 404)
    response = HttpResponse(png, content_type = "image/png")
    response["Cache-Control"] = "private, max-age=3600"
    return response


@require_GET
@login_required
def task_detail_json(request: HttpRequest, task_id: str) -> JsonResponse:
    userId = str(request.user.pk)
    task = tasksRepo.getTask(userId, str(task_id))
    if task is None:
        return JsonResponse({"error": "task not found"}, status = 404)
    executions = tasksRepo.listExecutionsForTask(userId, str(task_id))
    steps: list[dict] = []
    if executions:
        steps = tasksRepo.listStepsForExecution(userId, executions[0]["id"])
    return JsonResponse({"task": task, "executions": executions, "steps": steps})
