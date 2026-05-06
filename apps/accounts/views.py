"""User-facing preferences view.

Production persists preferences in Neo4j while local/test mode keeps the
legacy ORM record. Both paths share `UserPreferenceForm` so the template
surface remains unchanged.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from apps.accounts.forms import UserPreferenceForm
from apps.accounts.models import UserPreference


@login_required
def preferences(request: HttpRequest) -> HttpResponse:
    if getattr(settings, "CUTIEE_NEO4J_FRAMEWORK_AUTH", False):
        return _neo4jPreferences(request)

    pref, _ = UserPreference.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = UserPreferenceForm(request.POST, instance=pref)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse("accounts:preferences"))
    else:
        form = UserPreferenceForm(instance=pref)
    return render(
        request,
        "accounts/preferences.html",
        {"form": form, "preference": pref},
    )


def _neo4jPreferences(request: HttpRequest) -> HttpResponse:
    from apps.accounts import repo

    pref = UserPreference.for_user(request.user)
    if request.method == "POST":
        form = UserPreferenceForm(request.POST, instance=pref)
        if form.is_valid():
            repo.savePreference(
                userId=str(request.user.pk),
                theme=str(form.cleaned_data["theme"]),
                dashboardWindowDays=int(form.cleaned_data["dashboard_window_days"]),
                shouldRedactAuditScreenshots=bool(
                    form.cleaned_data["redact_audit_screenshots"]
                ),
            )
            return HttpResponseRedirect(reverse("accounts:preferences"))
    else:
        form = UserPreferenceForm(instance=pref)
    return render(
        request,
        "accounts/preferences.html",
        {"form": form, "preference": pref},
    )
