from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from agent.persistence.healthcheck import checkNeo4jReachable
from apps.audit.repo import auditCountForUser, listAuditForUser
from apps.common.query_utils import safeInt

PAGE_SIZE = 50

_logger = logging.getLogger("cutiee.audit_views")


@login_required
def audit_list(request: HttpRequest) -> HttpResponse:
    userId = str(request.user.pk)
    page = safeInt(request.GET.get("page"), default = 1, minimum = 1)

    total = 0
    entries: list = []
    maxPage = 1
    hasMore = False
    db_error = ""
    try:
        total = auditCountForUser(userId)
        maxPage = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 1
        if page > maxPage:
            page = maxPage
        offset = (page - 1) * PAGE_SIZE
        entries = listAuditForUser(userId, limit = PAGE_SIZE, offset = offset)
        hasMore = offset + len(entries) < total
    except Exception:  # noqa: BLE001 - fail soft for UI
        _logger.warning("Neo4j fetch failed for /audit/", exc_info = True)
        db_error = checkNeo4jReachable().remediation or "Database temporarily unavailable."

    return render(
        request,
        "audit/list.html",
        {
            "entries": entries,
            "total": total,
            "page": page,
            "max_page": maxPage,
            "has_more": hasMore,
            "db_error": db_error,
        },
    )
