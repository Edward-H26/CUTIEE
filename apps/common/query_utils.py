"""Shared helpers for parsing and validating HTTP query parameters.

Each Django view that accepts a numeric or string query param runs into
the same failure mode: int() on untrusted input raises ValueError and
Django hands the user a 500. Centralizing the pattern here means every
view degrades the same way and future views can reach for a tested
helper instead of rolling a try/except of their own.
"""

from __future__ import annotations


def safeInt(
    raw: str | None,
    *,
    default: int,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    """Parse an untrusted query-param int without letting ValueError escape.

    Returns `default` when `raw` is None, empty, or non-numeric. Clamps
    the parsed value to the [minimum, maximum] window so a huge value
    cannot slip through to a Cypher LIMIT and degrade the database.
    """
    if not raw:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed
