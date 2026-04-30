"""Centralized environment-variable parsers.

Every CUTIEE module that reads from `os.environ` should go through these
helpers so behavior on garbage input ("yes please", "tru", "") stays
consistent across the harness, the browser controller, the router, and
the screenshot store. The previous duplicated parsers in `config.py` and
`controller.py` disagreed on edge cases (one accepted "y", the other
didn't), which made `.env` debugging painful.
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "y", "on"}


def envInt(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def envFloat(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def envBool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in _TRUTHY


def envStr(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    return raw if raw else default
