"""Neo4j-backed bullet store, plugged into the agent's `BulletStore` protocol.

The Cypher specifics live here so the agent layer never imports the
Neo4j driver directly. Other consumers (tests, CLI tools, notebooks)
inject a different store via dependency injection.
"""
from __future__ import annotations

from typing import Any

from agent.memory.bullet import Bullet, DeltaUpdate
from apps.memory_app import repo as memoryRepo


class Neo4jBulletStore:
    """Adapter that fulfils `agent.memory.store.BulletStore`."""

    def loadAll(self, userId: str) -> list[Bullet]:
        return memoryRepo.listAllBulletObjectsForUser(userId)

    def upsertBullet(self, userId: str, bullet: Bullet) -> None:
        memoryRepo.upsertBullet(userId, bullet)

    def updateBulletFields(self, userId: str, bulletId: str, patch: dict[str, Any]) -> None:
        memoryRepo.updateBulletFields(userId, bulletId, patch)

    def removeBullet(self, userId: str, bulletId: str) -> None:
        memoryRepo.removeBullet(userId, bulletId)

    def applyDelta(self, userId: str, delta: DeltaUpdate) -> None:
        memoryRepo.applyDelta(userId, delta)
