"""Backwards-compatible re-export.

The canonical Bullet/DeltaUpdate schema now lives at `agent.memory.bullet`
so the agent package can be imported without Django. This module
re-exports those symbols so existing apps-side imports keep working.
"""
from __future__ import annotations

from agent.memory.bullet import (
    MEMORY_TYPES,
    TYPE_PRIORITY,
    Bullet,
    DeltaUpdate,
    hashContent,
)

__all__ = ["MEMORY_TYPES", "TYPE_PRIORITY", "Bullet", "DeltaUpdate", "hashContent"]
