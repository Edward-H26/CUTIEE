from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.audit.repo import list_audit_for_user


@login_required
def audit_list(request: HttpRequest) -> HttpResponse:
    entries = list_audit_for_user(str(request.user.pk))
    return render(request, "audit/list.html", {"entries": entries})
