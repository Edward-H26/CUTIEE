"""Template context processors for CUTIEE.

Injects deployment-level settings that several templates rely on but
that are not per-view (the noVNC URL, the CU backend label, etc.).
Keeping this here avoids sprinkling `os.environ` reads across views.
"""
from __future__ import annotations

import os


def runtime(request) -> dict[str, str]:
    del request  # request-agnostic; everything here is a deployment setting
    return {
        "NOVNC_URL": os.environ.get("CUTIEE_NOVNC_URL", "").strip(),
        "CUTIEE_CU_BACKEND": os.environ.get("CUTIEE_CU_BACKEND", "gemini"),
    }
