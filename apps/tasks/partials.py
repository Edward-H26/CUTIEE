"""HTMX-targeted HTML partials for the tasks app.

Keeping render helpers out of `api.py` lets the API module stay a thin
HTTP boundary. Any future polling endpoint that needs HTML output can
add a sibling helper here.
"""
from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe


def renderStatusPartial(snapshot: dict[str, Any]) -> HttpResponse:
    completed = bool(snapshot.get("completed"))
    finished = bool(snapshot.get("finished"))
    pillClass = "cutiee-pill--success" if completed else ("cutiee-pill--warning" if finished else "")
    pillLabel = "complete" if completed else ("finished" if finished else "running")

    tierBadges = _renderTierBadges(snapshot.get("tierUsage") or {})
    replayBadge: SafeString | str = (
        mark_safe("<span class='cutiee-pill cutiee-pill--accent'>replay</span>")
        if snapshot.get("replayed") else ""
    )
    reason = escape(snapshot.get("completionReason") or "")
    cost = f"{float(snapshot.get('totalCostUsd', 0.0) or 0.0):.4f}"

    pollAttrs: SafeString | str = mark_safe("")
    if not finished and snapshot.get("_pollUrl"):
        pollAttrs = format_html(
            " hx-get='{}' hx-trigger='every 2s' hx-swap='outerHTML' hx-target='this'",
            snapshot["_pollUrl"],
        )

    body = format_html(
        "<div id='exec-progress' class='cutiee-exec-progress'{poll}>"
        "<div class='cutiee-stack-tight'>"
        "<div class='cutiee-row cutiee-row--gap-2'>"
        "<span class='cutiee-pill {pillClass}'>{pillLabel}</span>"
        "{replayBadge}"
        "<span class='cutiee-text-sm cutiee-muted'>{reason}</span>"
        "</div>"
        "<div class='cutiee-row cutiee-row--gap-4 cutiee-text-sm cutiee-muted'>"
        "<span>steps: <strong class='cutiee-strong'>{steps}</strong></span>"
        "<span>spent: <strong class='cutiee-strong'>${cost}</strong></span>"
        "</div>"
        "<div class='cutiee-row cutiee-row--gap-2'>{tierBadges}</div>"
        "</div>"
        "</div>",
        poll = pollAttrs,
        pillClass = pillClass,
        pillLabel = pillLabel,
        replayBadge = replayBadge,
        reason = reason,
        steps = snapshot.get("stepCount", 0),
        cost = cost,
        tierBadges = tierBadges,
    )
    return HttpResponse(body)


def _renderTierBadges(tierUsage: dict[Any, int]) -> SafeString:
    if not tierUsage:
        return mark_safe("<span class='cutiee-text-sm cutiee-muted'>no tier data yet</span>")
    return format_html_join(
        "",
        "<span class='cutiee-pill'>T{}: {}</span>",
        ((tier, count) for tier, count in sorted(tierUsage.items(), key = lambda kv: int(kv[0]))),
    )


def renderApprovalModal(executionId: str, pending: dict[str, Any] | None) -> HttpResponse:
    """Render the approval-modal partial.

    Returns an empty container when nothing is pending so the polling
    endpoint can swap-out instead of leaving a stale modal up. The
    polling itself is wired in detail.html via hx-trigger=every 1s.
    """
    pollUrl = f"/tasks/api/approval/{executionId}/"
    if pending is None:
        return HttpResponse(format_html(
            "<div id='approval-slot' "
            "hx-get='{}' hx-trigger='every 1s' hx-swap='outerHTML' hx-target='this'></div>",
            pollUrl,
        ))
    approveUrl = f"/tasks/api/approval/{executionId}/approve/"
    rejectUrl = f"/tasks/api/approval/{executionId}/reject/"
    return HttpResponse(format_html(
        "<div id='approval-slot' class='cutiee-card cutiee-approval' "
        "hx-get='{poll}' hx-trigger='every 1s' hx-swap='outerHTML' hx-target='this'>"
        "<div class='cutiee-stack-tight'>"
        "<div class='cutiee-row cutiee-row--gap-2'>"
        "<span class='cutiee-pill cutiee-pill--danger'>{risk}</span>"
        "<strong>Approval needed</strong>"
        "</div>"
        "<div class='cutiee-text-sm'>{descr}</div>"
        "<div class='cutiee-row cutiee-row--gap-2'>"
        "<button class='cta' hx-post='{approve}' hx-swap='none'>Approve</button>"
        "<button class='cutiee-btn-ghost' hx-post='{reject}' hx-swap='none'>Reject</button>"
        "</div>"
        "</div>"
        "</div>",
        poll = pollUrl,
        risk = escape(pending.get("risk", "")),
        descr = escape(pending.get("actionDescription", "")),
        approve = approveUrl,
        reject = rejectUrl,
    ))
