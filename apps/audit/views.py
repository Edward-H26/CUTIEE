from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from agent.persistence.healthcheck import checkNeo4jReachable
from apps.audit.repo import auditCountForUser, listAuditForUser
from apps.common.query_utils import safeInt

PAGE_SIZE = 50

_logger = logging.getLogger("cutiee.audit_views")


class _CypherAuditWindow:
    """Adapter that lets django.core.paginator.Paginator drive Cypher pagination.

    Paginator wants an object with `count()` (or `len()`) plus slicing.
    The audit feed lives in Neo4j so we expose `count` from a dedicated
    Cypher rollup and translate the requested slice into the existing
    `listAuditForUser(limit, offset)` repo call instead of pulling the
    whole audit history into memory.
    """

    def __init__(self, userId: str, total: int) -> None:
        self._userId = userId
        self._total = total

    def count(self) -> int:
        return self._total

    def __len__(self) -> int:
        return self._total

    def __getitem__(self, key: slice) -> list:
        if not isinstance(key, slice):
            raise TypeError("Only slice access is supported")
        start = key.start or 0
        stop = key.stop if key.stop is not None else self._total
        limit = max(0, stop - start)
        if limit == 0:
            return []
        return listAuditForUser(self._userId, limit=limit, offset=start)


@login_required
def audit_list(request: HttpRequest) -> HttpResponse:
    userId = str(request.user.pk)
    page = safeInt(request.GET.get("page"), default=1, minimum=1)

    total = 0
    entries: list = []
    maxPage = 1
    hasMore = False
    db_error = ""
    try:
        total = auditCountForUser(userId)
        paginator = Paginator(_CypherAuditWindow(userId, total), PAGE_SIZE)
        pageObj = paginator.get_page(page)
        page = pageObj.number
        maxPage = paginator.num_pages
        entries = list(pageObj.object_list)
        hasMore = pageObj.has_next()
    except Exception:  # noqa: BLE001 - fail soft for UI
        _logger.warning("Neo4j fetch failed for /audit/", exc_info=True)
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
