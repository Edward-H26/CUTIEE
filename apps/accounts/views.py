"""User-facing preferences view backed by the UserPreference ORM model.

Pairs with `apps/accounts/models.py:UserPreference`, the small Django
ORM record that carries per-user UI preferences (theme, dashboard
window, audit screenshot redaction default). The view reads or creates
the row via the OneToOne accessor and renders a ModelForm; POST writes
through the form's save and redirects back to the preferences page.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from apps.accounts.forms import UserPreferenceForm
from apps.accounts.models import UserPreference


@login_required
def preferences(request: HttpRequest) -> HttpResponse:
    pref, _ = UserPreference.objects.get_or_create(user = request.user)
    if request.method == "POST":
        form = UserPreferenceForm(request.POST, instance = pref)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse("accounts:preferences"))
    else:
        form = UserPreferenceForm(instance = pref)
    return render(
        request,
        "accounts/preferences.html",
        {"form": form, "preference": pref},
    )
