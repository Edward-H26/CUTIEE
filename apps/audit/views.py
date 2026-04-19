from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.audit.repo import auditCountForUser, listAuditForUser

PAGE_SIZE = 50


@login_required
def audit_list(request: HttpRequest) -> HttpResponse:
    userId = str(request.user.pk)
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except (TypeError, ValueError):
        page = 1

    total = auditCountForUser(userId)
    maxPage = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 1
    if page > maxPage:
        page = maxPage

    offset = (page - 1) * PAGE_SIZE
    entries = listAuditForUser(userId, limit = PAGE_SIZE, offset = offset)
    hasMore = offset + len(entries) < total
    return render(
        request,
        "audit/list.html",
        {
            "entries": entries,
            "total": total,
            "page": page,
            "max_page": maxPage,
            "has_more": hasMore,
        },
    )
