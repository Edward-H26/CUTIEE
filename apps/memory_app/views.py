from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from agent.persistence.healthcheck import checkNeo4jReachable
from apps.memory_app.repo import (
    listBulletsForUser,
    listTemplatesForUser,
    markTemplateStale,
    memoryDashboardStats,
)

_logger = logging.getLogger("cutiee.memory_views")

_DEFAULT_STATS = {
    "bullet_count": 0,
    "template_count": 0,
    "stale_template_count": 0,
    "avg_strength": 0.0,
}


@login_required
def bullet_list(request: HttpRequest) -> HttpResponse:
    userId = str(request.user.pk)
    bullets: list = []
    templates: list = []
    stats = dict(_DEFAULT_STATS)
    db_error = ""
    try:
        bullets = listBulletsForUser(userId)
        templates = listTemplatesForUser(userId)
        stats = memoryDashboardStats(userId)
    except Exception:  # noqa: BLE001 - fail soft for UI
        _logger.warning("Neo4j fetch failed for /memory/", exc_info = True)
        db_error = checkNeo4jReachable().remediation or "Database temporarily unavailable."
    return render(
        request,
        "memory_app/list.html",
        {"bullets": bullets, "templates": templates, "stats": stats, "db_error": db_error},
    )


@login_required
def mark_stale(request: HttpRequest, template_id: str) -> HttpResponse:
    if request.method != "POST":
        return redirect("memory_app:list")
    markTemplateStale(
        userId = str(request.user.pk),
        templateId = str(template_id),
        reason = request.POST.get("reason", "user-marked"),
    )
    return redirect("memory_app:list")
