"""Verify UserPreference values actually drive runtime behavior.

The ORM model would be dead code if no view, template, or service ever
read its values. These tests pin the integration in three places:

1. `cost_timeseries` JSON view uses `dashboard_window_days` as the default
   when no `?days=` query param is set.
2. `?days=N` overrides the preference (URL still wins for ad-hoc poking).
3. The base template renders `theme-<value>` on the body class via the
   `userTheme` context processor.
"""
from __future__ import annotations

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.accounts.models import UserPreference


@pytest.mark.django_db
def test_costTimeseriesUsesPreferenceWhenNoQueryParam() -> None:
    user = get_user_model().objects.create_user(username = "pref-default", password = "pw")
    UserPreference.objects.create(user = user, dashboard_window_days = 30)
    client = Client()
    client.force_login(user)

    with mock.patch("apps.tasks.repo.costTimeseriesForUser", return_value = []) as fake:
        response = client.get(reverse("tasks:cost_timeseries"))
    assert response.status_code == 200
    fake.assert_called_once()
    call_kwargs = fake.call_args.kwargs
    assert call_kwargs["days"] == 30


@pytest.mark.django_db
def test_costTimeseriesQueryParamOverridesPreference() -> None:
    user = get_user_model().objects.create_user(username = "pref-override", password = "pw")
    UserPreference.objects.create(user = user, dashboard_window_days = 30)
    client = Client()
    client.force_login(user)

    with mock.patch("apps.tasks.repo.costTimeseriesForUser", return_value = []) as fake:
        response = client.get(reverse("tasks:cost_timeseries") + "?days=7")
    assert response.status_code == 200
    fake.assert_called_once()
    assert fake.call_args.kwargs["days"] == 7


@pytest.mark.django_db
def test_costTimeseriesUsesDefaultWhenNoPreferenceRow() -> None:
    user = get_user_model().objects.create_user(username = "pref-missing", password = "pw")
    client = Client()
    client.force_login(user)
    assert not UserPreference.objects.filter(user = user).exists()

    with mock.patch("apps.tasks.repo.costTimeseriesForUser", return_value = []) as fake:
        response = client.get(reverse("tasks:cost_timeseries"))
    assert response.status_code == 200
    assert fake.call_args.kwargs["days"] == 14


@pytest.mark.django_db
def test_themeContextProcessorOnBodyClass() -> None:
    user = get_user_model().objects.create_user(username = "theme-user", password = "pw")
    UserPreference.objects.create(user = user, theme = "slate")
    client = Client()
    client.force_login(user)

    response = client.get(reverse("landing:about"))
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "theme-slate" in body


@pytest.mark.django_db
def test_themeDefaultsToAuroraForAnonymous() -> None:
    client = Client()
    response = client.get(reverse("landing:about"))
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "theme-aurora" in body


@pytest.mark.django_db
def test_userPreferenceForUserHandlesAnonymous() -> None:
    pref = UserPreference.for_user(None)
    assert pref.theme == "aurora"
    assert pref.dashboard_window_days == 14
    assert pref.redact_audit_screenshots is True


@pytest.mark.django_db
def test_userPreferenceForUserMissingRowReturnsUnsavedDefault() -> None:
    user = get_user_model().objects.create_user(username = "no-pref", password = "pw")
    pref = UserPreference.for_user(user)
    assert pref.pk is None
    assert pref.theme == "aurora"
    assert pref.dashboard_window_days == 14


@pytest.mark.django_db
def test_userPreferenceForUserExistingRow() -> None:
    user = get_user_model().objects.create_user(username = "has-pref", password = "pw")
    UserPreference.objects.create(user = user, theme = "slate", dashboard_window_days = 60)
    pref = UserPreference.for_user(user)
    assert pref.pk is not None
    assert pref.theme == "slate"
    assert pref.dashboard_window_days == 60
