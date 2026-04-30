"""Tests for the UserPreference form-view at /me/preferences/.

Covers the OneToOne get-or-create flow, the GET render, and the POST
update path. The model layer is exercised separately in
`test_accounts_models.py`; this file focuses on the view contract.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.accounts.models import UserPreference


@pytest.mark.django_db
def test_preferencesViewRequiresLogin() -> None:
    client = Client()
    response = client.get("/me/preferences/")
    assert response.status_code in {302, 401, 403}


@pytest.mark.django_db
def test_preferencesGetCreatesRowAndRenders() -> None:
    user = get_user_model().objects.create_user(username="pref-get", password="pw")
    client = Client()
    client.force_login(user)

    response = client.get(reverse("accounts:preferences"))
    assert response.status_code == 200
    assert UserPreference.objects.filter(user=user).exists()
    body = response.content.decode("utf-8")
    assert "preferences" in body.lower()


@pytest.mark.django_db
def test_preferencesPostUpdates() -> None:
    user = get_user_model().objects.create_user(username="pref-post", password="pw")
    UserPreference.objects.create(user=user)
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("accounts:preferences"),
        {
            "theme": "slate",
            "dashboard_window_days": 30,
            "redact_audit_screenshots": "on",
        },
    )
    assert response.status_code in {200, 302}

    pref = UserPreference.objects.get(user=user)
    assert pref.theme == "slate"
    assert pref.dashboard_window_days == 30
    assert pref.redact_audit_screenshots is True
