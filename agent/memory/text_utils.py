"""Shared text utilities used across memory modules.

Extracted from `reflector.py` and `decomposer.py` to eliminate the
duplicate implementations of `_slugify` and `_parseJsonLoose`. Also
hosts `_stepIndexFromContent`, which was duplicated across
`replay.py` and `fragment_replay.py`.

These helpers stay dependency-free so they import cheaply from any
caller in the memory layer.
"""
from __future__ import annotations

import json
import re
from typing import Any

_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_STEP_INDEX_PATTERN = re.compile(r"step_index=(\d+)")


def slugify(text: str) -> str:
    """Kebab-case slug up to 48 characters; safe for tags and topics."""
    if not text:
        return "task"
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    return text.strip("-")[:48] or "task"


def parseJsonLoose(text: str) -> Any:
    """Best-effort JSON parser used by the LLM reflector and decomposer.

    Tolerates Markdown fence wrappers and narrative prefixes by
    extracting the first balanced object if strict parsing fails.
    Returns None on total failure so callers can fall back rather than
    propagating a JSONDecodeError through the pipeline.
    """
    if not text:
        return None
    if text.startswith("```"):
        parts = text.split("\n")
        if len(parts) > 2:
            text = "\n".join(parts[1:-1]).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_PATTERN.search(text)
        if match is None:
            return None
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None


def stepIndexFromContent(content: str) -> int:
    """Recover the `step_index=N` integer from a bullet content string."""
    if not content:
        return 0
    match = _STEP_INDEX_PATTERN.search(content)
    return int(match.group(1)) if match else 0
