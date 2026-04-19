from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.memory_app.repo import (
    listBulletsForUser,
    listTemplatesForUser,
    markTemplateStale,
    memoryDashboardStats,
)


@login_required
def bullet_list(request: HttpRequest) -> HttpResponse:
    userId = str(request.user.pk)
    bullets = listBulletsForUser(userId)
    templates = listTemplatesForUser(userId)
    stats = memoryDashboardStats(userId)
    return render(
        request,
        "memory_app/list.html",
        {"bullets": bullets, "templates": templates, "stats": stats},
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
