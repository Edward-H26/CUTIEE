"""Curator — turn accepted lessons into a `DeltaUpdate`.

The curator merges new lessons into the existing bullet store rather than
blindly appending. Three branches:

* lesson matches an existing bullet (cosine >= 0.90 OR identical content
  hash) → emit `update_bullets[id] = {helpful_count: +1}` so the existing
  bullet's strength grows.
* lesson explicitly supersedes a bullet (`replacementForBulletId`) → emit
  both an `update_bullets` patch decreasing strength on the original and a
  `new_bullets` entry for the replacement, plus a `remove_bullets` reference
  if the original is fully obsoleted.
* otherwise → emit a fresh `Bullet` with type heuristics applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .embeddings import cosineSimilarity, defaultUseHashEmbedding, embedTexts
from .reflector import (
    EPISODIC_HINTS,
    PROCEDURAL_HINTS,
    SEMANTIC_HINTS,
    LessonCandidate,
)
from .bullet import Bullet, DeltaUpdate, hashContent

CONTENT_DEDUP_THRESHOLD = 0.90


@dataclass
class Curator:
    useHashEmbedding: bool = field(default_factory = defaultUseHashEmbedding)

    def curate(
        self,
        accepted: list[LessonCandidate],
        existing: list[Bullet],
    ) -> DeltaUpdate:
        delta = DeltaUpdate()
        if not accepted:
            return delta

        existingByHash: dict[str, Bullet] = {b.content_hash: b for b in existing if b.content_hash}
        existingEmbeddings: list[tuple[Bullet, list[float]]] = [
            (b, b.embedding) for b in existing if b.embedding
        ]

        for lesson in accepted:
            memoryType = self._inferMemoryType(lesson)
            contentHash = hashContent(lesson.content)

            duplicate = existingByHash.get(contentHash)
            if duplicate is None:
                duplicate = self._findEmbeddingDuplicate(lesson, existingEmbeddings)

            if duplicate is not None:
                patch = delta.update_bullets.setdefault(duplicate.id, {})
                patch["helpful_count"] = duplicate.helpful_count + 1 + patch.get("helpful_count", 0) - duplicate.helpful_count
                if memoryType == duplicate.memory_type:
                    bonusKey = f"{memoryType}_strength"
                    boosted = getattr(duplicate, bonusKey, 0.0) + 0.5
                    patch[bonusKey] = min(boosted, 5.0)
                continue

            if lesson.replacementForBulletId:
                supersededPatch = delta.update_bullets.setdefault(lesson.replacementForBulletId, {})
                supersededPatch["harmful_count"] = supersededPatch.get("harmful_count", 0) + 1
                supersededPatch["procedural_strength"] = max(
                    0.0,
                    supersededPatch.get("procedural_strength", 0.0) - 1.0,
                )

            embedding = embedTexts([lesson.content], useHashFallback = self.useHashEmbedding)[0]
            bullet = Bullet(
                content = lesson.content,
                memory_type = memoryType,
                tags = list(lesson.tags),
                topic = lesson.topic,
                concept = lesson.concept,
                content_hash = contentHash,
                embedding = embedding,
                helpful_count = 0,
                harmful_count = 0,
            )
            delta.new_bullets.append(bullet)

        return delta

    def _findEmbeddingDuplicate(
        self,
        lesson: LessonCandidate,
        existingEmbeddings: list[tuple[Bullet, list[float]]],
    ) -> Bullet | None:
        if not existingEmbeddings:
            return None
        lessonEmbedding = embedTexts(
            [lesson.content], useHashFallback = self.useHashEmbedding
        )[0]
        for bullet, embedding in existingEmbeddings:
            if cosineSimilarity(lessonEmbedding, embedding) >= CONTENT_DEDUP_THRESHOLD:
                return bullet
        return None

    def _inferMemoryType(self, lesson: LessonCandidate) -> str:
        if lesson.memoryType in {"semantic", "episodic", "procedural"}:
            return lesson.memoryType
        text = lesson.content.lower()
        if any(hint in text for hint in PROCEDURAL_HINTS):
            return "procedural"
        if any(hint in text for hint in EPISODIC_HINTS):
            return "episodic"
        if any(hint in text for hint in SEMANTIC_HINTS):
            return "semantic"
        return "semantic"
