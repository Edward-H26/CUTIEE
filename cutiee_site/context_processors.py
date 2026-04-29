"""Template context processors for CUTIEE.

Injects deployment-level settings that several templates rely on but
that are not per-view (the noVNC URL, the CU backend label, etc.).
Keeping this here avoids sprinkling `os.environ` reads across views.
"""
from __future__ import annotations

import os
from typing import Any


def runtime(request: Any) -> dict[str, str]:
    del request  # request-agnostic; everything here is a deployment setting
    return {
        "NOVNC_URL": os.environ.get("CUTIEE_NOVNC_URL", "").strip(),
        "CUTIEE_CU_BACKEND": os.environ.get("CUTIEE_CU_BACKEND", "gemini"),
    }


def userTheme(request: Any) -> dict[str, str]:
    """Inject the active theme name resolved from `UserPreference`.

    Anonymous users get the default `aurora` theme so the body class
    branch in `base.html` always has a value. Logged-in users see their
    saved choice. The unsaved-default `for_user` accessor avoids hitting
    the DB or creating a row for users who have never opened
    `/me/preferences/`.
    """
    from apps.accounts.models import UserPreference

    user = getattr(request, "user", None)
    pref = UserPreference.for_user(user)
    return {"USER_THEME": str(pref.theme)}
