from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import UserPreference


@pytest.mark.django_db
def test_userPreferenceDefaults() -> None:
    user = get_user_model().objects.create_user(username="prefs", password="pw")
    pref = UserPreference.objects.create(user=user)

    assert pref.theme == UserPreference.Theme.AURORA
    assert pref.dashboard_window_days == 14
    assert pref.redact_audit_screenshots is True
    assert str(pref).startswith("UserPreference(")
