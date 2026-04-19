"""ACE memory bullet schema.

Ported verbatim from the LongTermMemoryBasedSelfEvolvingAlgorithm reference
implementation. Each bullet carries three independent strength channels;
retrieval ranks by the sum of decayed strengths plus relevance and a type
priority. `DeltaUpdate` is what the curator emits at the end of every
execution: a compact patch that the memory layer can apply atomically.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MEMORY_TYPES = ("semantic", "episodic", "procedural")
TYPE_PRIORITY = {"procedural": 1.0, "episodic": 0.7, "semantic": 0.4}


def _nowUtc() -> datetime:
    return datetime.now(timezone.utc)


def hashContent(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


@dataclass
class Bullet:
    id: str = field(default_factory = lambda: str(uuid.uuid4()))
    content: str = ""
    memory_type: str = "semantic"
    tags: list[str] = field(default_factory = list)
    topic: str = ""
    concept: str = ""
    content_hash: str = ""
    context_scope_id: str = ""
    learner_id: str = ""
    helpful_count: int = 0
    harmful_count: int = 0
    semantic_strength: float = 0.0
    episodic_strength: float = 0.0
    procedural_strength: float = 0.0
    semantic_access_index: int = 0
    episodic_access_index: int = 0
    procedural_access_index: int = 0
    semantic_last_access: datetime | None = None
    episodic_last_access: datetime | None = None
    procedural_last_access: datetime | None = None
    ttl_days: int | None = None
    embedding: list[float] | None = None
    is_seed: bool = False
    is_credential: bool = False
    created_at: datetime = field(default_factory = _nowUtc)
    last_used: datetime = field(default_factory = _nowUtc)

    def __post_init__(self) -> None:
        if not self.content_hash and self.content:
            self.content_hash = hashContent(self.content)
        if self.memory_type not in MEMORY_TYPES:
            raise ValueError(f"memory_type must be one of {MEMORY_TYPES}, got {self.memory_type!r}")
        if self.memory_type == "semantic" and self.semantic_strength == 0.0:
            self.semantic_strength = 1.0
        if self.memory_type == "episodic" and self.episodic_strength == 0.0:
            self.episodic_strength = 1.0
        if self.memory_type == "procedural" and self.procedural_strength == 0.0:
            self.procedural_strength = 1.0

    def totalStrength(self) -> float:
        return self.semantic_strength + self.episodic_strength + self.procedural_strength

    def typePriority(self) -> float:
        return TYPE_PRIORITY[self.memory_type]

    def asNeo4jProps(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type,
            "tags": list(self.tags),
            "topic": self.topic,
            "concept": self.concept,
            "content_hash": self.content_hash,
            "context_scope_id": self.context_scope_id,
            "learner_id": self.learner_id,
            "helpful_count": self.helpful_count,
            "harmful_count": self.harmful_count,
            "semantic_strength": self.semantic_strength,
            "episodic_strength": self.episodic_strength,
            "procedural_strength": self.procedural_strength,
            "semantic_access_index": self.semantic_access_index,
            "episodic_access_index": self.episodic_access_index,
            "procedural_access_index": self.procedural_access_index,
            "semantic_last_access": self.semantic_last_access.isoformat() if self.semantic_last_access else None,
            "episodic_last_access": self.episodic_last_access.isoformat() if self.episodic_last_access else None,
            "procedural_last_access": self.procedural_last_access.isoformat() if self.procedural_last_access else None,
            "ttl_days": self.ttl_days,
            "embedding": self.embedding,
            "is_seed": self.is_seed,
            "is_credential": self.is_credential,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat(),
        }

    @classmethod
    def fromNeo4j(cls, row: dict[str, Any]) -> "Bullet":
        return cls(
            id = row.get("id", str(uuid.uuid4())),
            content = row.get("content", ""),
            memory_type = row.get("memory_type", "semantic"),
            tags = list(row.get("tags") or []),
            topic = row.get("topic", "") or "",
            concept = row.get("concept", "") or "",
            content_hash = row.get("content_hash", "") or "",
            context_scope_id = row.get("context_scope_id", "") or "",
            learner_id = row.get("learner_id", "") or "",
            helpful_count = int(row.get("helpful_count") or 0),
            harmful_count = int(row.get("harmful_count") or 0),
            semantic_strength = float(row.get("semantic_strength") or 0.0),
            episodic_strength = float(row.get("episodic_strength") or 0.0),
            procedural_strength = float(row.get("procedural_strength") or 0.0),
            semantic_access_index = int(row.get("semantic_access_index") or 0),
            episodic_access_index = int(row.get("episodic_access_index") or 0),
            procedural_access_index = int(row.get("procedural_access_index") or 0),
            ttl_days = row.get("ttl_days"),
            embedding = row.get("embedding"),
            is_seed = bool(row.get("is_seed") or False),
            is_credential = bool(row.get("is_credential") or False),
            created_at = _parseIso(row.get("created_at")),
            last_used = _parseIso(row.get("last_used")),
        )


@dataclass
class DeltaUpdate:
    new_bullets: list[Bullet] = field(default_factory = list)
    update_bullets: dict[str, dict[str, Any]] = field(default_factory = dict)
    remove_bullets: list[str] = field(default_factory = list)
    metadata: dict[str, Any] = field(default_factory = dict)

    def isEmpty(self) -> bool:
        return not (self.new_bullets or self.update_bullets or self.remove_bullets)


def _parseIso(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo = timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo = timezone.utc)
        except ValueError:
            pass
    return _nowUtc()
