"""ACEMemory — three-strength bullet store with retrieval/decay/refine.

The store is intentionally lightweight: it loads bullets for a single user
into memory, ranks them by `0.60 * relevance + 0.20 * total_strength + 0.20 *
type_priority` plus facet bonuses, and persists every mutation back through
the Cypher repos. The math comes from the LongTermMemoryBasedSelfEvolving
reference implementation; only the persistence layer differs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent.memory.decay import (
    EPISODIC_DECAY_RATE,
    PROCEDURAL_DECAY_RATE,
    SEMANTIC_DECAY_RATE,
    channelDecayedStrength,
    dominantChannel,
    totalDecayedStrength,
)
from agent.memory.embeddings import cosineSimilarity, embedTexts
from apps.memory_app import repo as memoryRepo
from apps.memory_app.bullet import Bullet, DeltaUpdate

LEARNED_BONUS = 0.08
SEED_PENALTY = 0.25
NEEDS_VISUAL_BONUS = 0.20
PERSONA_BONUS = 0.10
LEARNED_FLOOR = 2

NORMALIZED_STRENGTH_DENOM = 3.0  # max possible (1.0 per channel)


@dataclass
class ACEMemory:
    userId: str
    maxBullets: int = 100
    accessClock: int = 0
    bullets: dict[str, Bullet] = field(default_factory = dict)
    useHashEmbedding: bool = True
    loaded: bool = False

    def loadFromStore(self) -> None:
        self.bullets.clear()
        for bullet in memoryRepo.listAllBulletObjectsForUser(self.userId):
            self.bullets[bullet.id] = bullet
        self.loaded = True

    def ensureLoaded(self) -> None:
        if not self.loaded:
            self.loadFromStore()

    def advanceClock(self) -> int:
        self.accessClock += 1
        return self.accessClock

    def retrieveRelevantBullets(
        self,
        query: str,
        *,
        k: int = 8,
        facets: dict[str, Any] | None = None,
    ) -> list[Bullet]:
        self.ensureLoaded()
        self.advanceClock()
        if not self.bullets:
            return []
        facets = facets or {}
        queryEmbedding = embedTexts([query], useHashFallback = self.useHashEmbedding)[0]

        scored: list[tuple[float, str, Bullet]] = []
        for bullet in self.bullets.values():
            if bullet.is_credential:
                continue
            score = self._scoreBullet(bullet, queryEmbedding, facets)
            scored.append((score, dominantChannel(bullet, self.accessClock), bullet))

        scored.sort(key = lambda item: item[0], reverse = True)
        topK = scored[:k]

        learnedTopK = [item for item in topK if not item[2].is_seed]
        if len(learnedTopK) < LEARNED_FLOOR:
            for triple in scored[k:]:
                if not triple[2].is_seed:
                    topK.append(triple)
                    learnedTopK.append(triple)
                if len(learnedTopK) >= LEARNED_FLOOR:
                    break

        returned: list[Bullet] = []
        nowIso = datetime.now(timezone.utc).isoformat()
        for _, channel, bullet in topK[:k]:
            self._touchBullet(bullet, channel, nowIso)
            returned.append(bullet)
        return returned

    def _scoreBullet(
        self,
        bullet: Bullet,
        queryEmbedding: list[float],
        facets: dict[str, Any],
    ) -> float:
        relevance = 0.0
        if bullet.embedding:
            relevance = cosineSimilarity(queryEmbedding, bullet.embedding)
        else:
            bullet.embedding = embedTexts([bullet.content], useHashFallback = self.useHashEmbedding)[0]
            relevance = cosineSimilarity(queryEmbedding, bullet.embedding)
        relevance = max(0.0, relevance)

        normalizedStrength = totalDecayedStrength(bullet, self.accessClock) / NORMALIZED_STRENGTH_DENOM

        score = (
            0.60 * relevance
            + 0.20 * normalizedStrength
            + 0.20 * bullet.typePriority()
        )

        if not bullet.is_seed:
            score += LEARNED_BONUS
        else:
            score -= SEED_PENALTY

        if facets.get("needs_visual") and "visual" in bullet.tags:
            score += NEEDS_VISUAL_BONUS
        if facets.get("persona_request") and "persona" in bullet.tags:
            score += PERSONA_BONUS
        if facets.get("need_procedural") and bullet.memory_type == "procedural":
            score += 0.10
        if facets.get("topic") and bullet.topic == facets["topic"]:
            score += 0.15

        return score

    def _touchBullet(self, bullet: Bullet, channel: str, nowIso: str) -> None:
        patch: dict[str, Any] = {"helpful_count": bullet.helpful_count + 1}
        if channel == "semantic":
            bullet.semantic_access_index = self.accessClock
            patch["semantic_access_index"] = self.accessClock
            patch["semantic_last_access"] = nowIso
        elif channel == "episodic":
            bullet.episodic_access_index = self.accessClock
            patch["episodic_access_index"] = self.accessClock
            patch["episodic_last_access"] = nowIso
        elif channel == "procedural":
            bullet.procedural_access_index = self.accessClock
            patch["procedural_access_index"] = self.accessClock
            patch["procedural_last_access"] = nowIso
        bullet.helpful_count += 1
        memoryRepo.updateBulletFields(self.userId, bullet.id, patch)

    def applyDelta(self, delta: DeltaUpdate) -> None:
        self.ensureLoaded()
        if delta.isEmpty():
            return
        for bullet in delta.new_bullets:
            if not bullet.embedding:
                bullet.embedding = embedTexts(
                    [bullet.content], useHashFallback = self.useHashEmbedding
                )[0]
            self.bullets[bullet.id] = bullet

        for bulletId, patch in delta.update_bullets.items():
            existing = self.bullets.get(bulletId)
            if existing is None:
                continue
            for key, value in patch.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)

        for bulletId in delta.remove_bullets:
            self.bullets.pop(bulletId, None)

        memoryRepo.applyDelta(self.userId, delta)

    def refine(self) -> int:
        """Dedup similar bullets and prune below `maxBullets`. Returns deletions."""
        self.ensureLoaded()
        if len(self.bullets) <= self.maxBullets:
            return 0

        ranked = sorted(
            self.bullets.values(),
            key = lambda b: totalDecayedStrength(b, self.accessClock) + 0.1 * b.helpful_count,
            reverse = True,
        )

        keepers: list[Bullet] = []
        toRemove: list[str] = []
        for bullet in ranked:
            duplicate = False
            for kept in keepers:
                if cosineSimilarity(bullet.embedding, kept.embedding) >= 0.85:
                    duplicate = True
                    break
            if duplicate:
                toRemove.append(bullet.id)
            else:
                keepers.append(bullet)
            if len(keepers) >= self.maxBullets:
                break

        for bullet in ranked[len(keepers) + len(toRemove):]:
            toRemove.append(bullet.id)

        if toRemove:
            self.applyDelta(DeltaUpdate(remove_bullets = toRemove))
        return len(toRemove)

    def asPromptBlock(self, bullets: list[Bullet]) -> str:
        if not bullets:
            return ""
        lines = ["[prior knowledge]"]
        for bullet in bullets:
            if bullet.is_credential:
                continue
            tag = f" tags={','.join(bullet.tags)}" if bullet.tags else ""
            lines.append(f"- ({bullet.memory_type}){tag} {bullet.content}")
        return "\n".join(lines)

    def channelStrength(self, bullet: Bullet, channel: str) -> float:
        return channelDecayedStrength(bullet, channel, self.accessClock)

    @property
    def decayRates(self) -> dict[str, float]:
        return {
            "semantic": SEMANTIC_DECAY_RATE,
            "episodic": EPISODIC_DECAY_RATE,
            "procedural": PROCEDURAL_DECAY_RATE,
        }
