"""Persistence-agnostic interface for the ACE bullet store.

Lets the agent layer stay portable. Django callers inject the
`Neo4jBulletStore` from `apps/memory_app/store.py`; tests, notebooks,
and any non-Django consumer can use `InMemoryBulletStore` (or write
their own implementation) without depending on Django settings,
allauth, or the Neo4j driver.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from .bullet import Bullet, DeltaUpdate


class BulletStore(Protocol):
    """Minimal contract a backing store must satisfy for ACEMemory."""

    def loadAll(self, userId: str) -> list[Bullet]: ...

    def upsertBullet(self, userId: str, bullet: Bullet) -> None: ...

    def updateBulletFields(self, userId: str, bulletId: str, patch: dict[str, Any]) -> None: ...

    def removeBullet(self, userId: str, bulletId: str) -> None: ...

    def applyDelta(self, userId: str, delta: DeltaUpdate) -> None: ...


class InMemoryBulletStore:
    """Dict-backed store. Useful for tests, notebooks, single-process demos."""

    def __init__(self) -> None:
        self._buckets: dict[str, dict[str, Bullet]] = {}

    def _bucket(self, userId: str) -> dict[str, Bullet]:
        return self._buckets.setdefault(userId, {})

    def loadAll(self, userId: str) -> list[Bullet]:
        return list(self._bucket(userId).values())

    def upsertBullet(self, userId: str, bullet: Bullet) -> None:
        self._bucket(userId)[bullet.id] = bullet

    def updateBulletFields(self, userId: str, bulletId: str, patch: dict[str, Any]) -> None:
        bullet = self._bucket(userId).get(bulletId)
        if bullet is None:
            return
        for key, value in patch.items():
            if hasattr(bullet, key):
                setattr(bullet, key, value)

    def removeBullet(self, userId: str, bulletId: str) -> None:
        self._bucket(userId).pop(bulletId, None)

    def applyDelta(self, userId: str, delta: DeltaUpdate) -> None:
        for bullet in delta.new_bullets:
            self.upsertBullet(userId, bullet)
        for bulletId, patch in delta.update_bullets.items():
            self.updateBulletFields(userId, bulletId, patch)
        for bulletId in delta.remove_bullets:
            self.removeBullet(userId, bulletId)


def collectBullets(stores: Iterable[BulletStore], userId: str) -> list[Bullet]:
    """Convenience helper: union the bullets across multiple stores."""
    seen: dict[str, Bullet] = {}
    for store in stores:
        for bullet in store.loadAll(userId):
            seen.setdefault(bullet.id, bullet)
    return list(seen.values())
