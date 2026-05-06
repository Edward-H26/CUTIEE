"""Cypher-backed repos for `:MemoryBullet` and `:ProceduralTemplate` nodes.

`MemoryBulletRepo` mirrors the in-memory ACE store into Neo4j. `TemplateRepo`
keeps a separate `ProceduralTemplate` aggregate that the replay planner reads
to find existing reusable workflows. The two surfaces stay independent so the
ACE pipeline can evolve without touching the template view shown in the UI.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from agent.persistence.neo4j_client import run_query, run_single
from apps.memory_app.bullet import Bullet, DeltaUpdate, humanReadableBulletContent


class MemoryBulletRow(dict[str, Any]):
    """Linkable memory-bullet row for template rendering."""

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return f"{reverse('memory_app:list')}#bullet-{self['id']}"


class TemplateRow(dict[str, Any]):
    """Linkable procedural-template row for template rendering.

    Templates render inside the memory dashboard with the bullet store, so the
    absolute URL targets the same dashboard and anchors to the row id when the
    template is present on the current page.
    """

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return f"{reverse('memory_app:list')}#template-{self['id']}"


def _nowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serializeEmbedding(embedding: list[float] | None) -> str | None:
    return json.dumps(embedding) if embedding else None


def _deserializeEmbedding(raw: Any) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return [float(x) for x in raw]
    try:
        parsed = json.loads(raw)
        return [float(x) for x in parsed] if isinstance(parsed, list) else None
    except (TypeError, ValueError):
        return None


def upsertBullet(userId: str, bullet: Bullet) -> None:
    props = bullet.asNeo4jProps()
    props["embedding"] = _serializeEmbedding(bullet.embedding)
    run_query(
        """
        MERGE (u:User {id: $user_id})
        MERGE (b:MemoryBullet {id: $id})
        SET b.user_id = $user_id,
            b.content = $content,
            b.human_content = $human_content,
            b.memory_type = $memory_type,
            b.tags = $tags,
            b.topic = $topic,
            b.concept = $concept,
            b.content_hash = $content_hash,
            b.context_scope_id = $context_scope_id,
            b.learner_id = $learner_id,
            b.helpful_count = $helpful_count,
            b.harmful_count = $harmful_count,
            b.semantic_strength = $semantic_strength,
            b.episodic_strength = $episodic_strength,
            b.procedural_strength = $procedural_strength,
            b.semantic_access_index = $semantic_access_index,
            b.episodic_access_index = $episodic_access_index,
            b.procedural_access_index = $procedural_access_index,
            b.semantic_last_access = $semantic_last_access,
            b.episodic_last_access = $episodic_last_access,
            b.procedural_last_access = $procedural_last_access,
            b.ttl_days = $ttl_days,
            b.embedding = $embedding,
            b.is_seed = $is_seed,
            b.is_credential = $is_credential,
            b.created_at = coalesce(b.created_at, $created_at),
            b.last_used = $last_used
        MERGE (u)-[:HOLDS]->(b)
        """,
        user_id=str(userId),
        **props,
    )


def updateBulletFields(userId: str, bulletId: str, patch: dict[str, Any]) -> None:
    if not patch:
        return
    setFragments: list[str] = []
    params: dict[str, Any] = {"user_id": str(userId), "id": bulletId, "now": _nowIso()}
    for key, value in patch.items():
        if key == "embedding":
            params["embedding"] = _serializeEmbedding(value)
            setFragments.append("b.embedding = $embedding")
            continue
        params[key] = value
        setFragments.append(f"b.{key} = ${key}")
    if "content" in patch and "human_content" not in patch:
        params["human_content"] = humanReadableBulletContent(
            str(patch.get("content") or ""),
            str(patch.get("memory_type") or ""),
        )
        setFragments.append("b.human_content = $human_content")
    setFragments.append("b.last_used = $now")
    cypher = "MATCH (u:User {id: $user_id})-[:HOLDS]->(b:MemoryBullet {id: $id})\nSET " + ", ".join(
        setFragments
    )
    run_query(cypher, **params)


def removeBullet(userId: str, bulletId: str) -> None:
    run_query(
        """
        MATCH (u:User {id: $user_id})-[:HOLDS]->(b:MemoryBullet {id: $id})
        DETACH DELETE b
        """,
        user_id=str(userId),
        id=bulletId,
    )


def applyDelta(userId: str, delta: DeltaUpdate) -> None:
    for bullet in delta.new_bullets:
        upsertBullet(userId=userId, bullet=bullet)
    for bulletId, patch in delta.update_bullets.items():
        updateBulletFields(userId=userId, bulletId=bulletId, patch=patch)
    for bulletId in delta.remove_bullets:
        removeBullet(userId=userId, bulletId=bulletId)


def listBulletsForUser(userId: str) -> list[MemoryBulletRow]:
    rows = run_query(
        """
        MATCH (u:User {id: $user_id})-[:HOLDS]->(b:MemoryBullet)
        RETURN b.id AS id,
               b.content AS content,
               b.human_content AS human_content,
               b.memory_type AS memory_type,
               b.tags AS tags,
               b.helpful_count AS helpful_count,
               b.harmful_count AS harmful_count,
               b.semantic_strength AS semantic_strength,
               b.episodic_strength AS episodic_strength,
               b.procedural_strength AS procedural_strength,
               b.topic AS topic,
               b.concept AS concept,
               b.is_seed AS is_seed
        ORDER BY b.procedural_strength + b.episodic_strength + b.semantic_strength DESC
        """,
        user_id=str(userId),
    )
    out: list[MemoryBulletRow] = []
    for row in rows:
        row["human_content"] = row.get("human_content") or humanReadableBulletContent(
            str(row.get("content") or ""),
            str(row.get("memory_type") or ""),
        )
        out.append(MemoryBulletRow(row))
    return out


def listAllBulletObjectsForUser(userId: str) -> list[Bullet]:
    rows = run_query(
        """
        MATCH (u:User {id: $user_id})-[:HOLDS]->(b:MemoryBullet)
        RETURN b {.*} AS bullet
        """,
        user_id=str(userId),
    )
    bullets: list[Bullet] = []
    for row in rows:
        raw = dict(row["bullet"])
        raw["embedding"] = _deserializeEmbedding(raw.get("embedding"))
        bullets.append(Bullet.fromNeo4j(raw))
    return bullets


# list_bullets_for_user kept for backwards-compatible imports
list_bullets_for_user = listBulletsForUser


def getBullet(userId: str, bulletId: str) -> Bullet | None:
    row = run_single(
        """
        MATCH (u:User {id: $user_id})-[:HOLDS]->(b:MemoryBullet {id: $id})
        RETURN b {.*} AS bullet
        """,
        user_id=str(userId),
        id=bulletId,
    )
    if row is None:
        return None
    raw = dict(row["bullet"])
    raw["embedding"] = _deserializeEmbedding(raw.get("embedding"))
    return Bullet.fromNeo4j(raw)


def upsertTemplate(
    userId: str,
    *,
    templateId: str | None = None,
    description: str,
    domain: str,
    embedding: list[float] | None,
    actions: list[dict[str, Any]],
    successCount: int = 0,
    stale: bool = False,
) -> str:
    templateId = templateId or str(uuid.uuid4())
    run_query(
        """
        MERGE (u:User {id: $user_id})
        MERGE (t:ProceduralTemplate {id: $id})
        SET t.description = $description,
            t.domain = $domain,
            t.embedding = $embedding,
            t.actions_json = $actions_json,
            t.success_count = coalesce(t.success_count, 0) + $success_count,
            t.stale = $stale,
            t.updated_at = $updated_at,
            t.created_at = coalesce(t.created_at, $updated_at)
        MERGE (u)-[:OWNS_TEMPLATE]->(t)
        """,
        user_id=str(userId),
        id=templateId,
        description=description,
        domain=domain,
        embedding=_serializeEmbedding(embedding),
        actions_json=json.dumps(actions),
        success_count=int(successCount),
        stale=bool(stale),
        updated_at=_nowIso(),
    )
    return templateId


def listTemplatesForUser(userId: str) -> list[TemplateRow]:
    rows = run_query(
        """
        MATCH (u:User {id: $user_id})-[:OWNS_TEMPLATE]->(t:ProceduralTemplate)
        RETURN t {.*} AS template
        ORDER BY t.updated_at DESC
        """,
        user_id=str(userId),
    )
    out: list[TemplateRow] = []
    for row in rows:
        template = TemplateRow(row["template"])
        actionsJson = template.get("actions_json")
        try:
            template["actions"] = json.loads(actionsJson) if actionsJson else []
        except (TypeError, ValueError):
            template["actions"] = []
        template.pop("actions_json", None)
        template["embedding"] = _deserializeEmbedding(template.get("embedding"))
        out.append(template)
    return out


def getTemplate(userId: str, templateId: str) -> TemplateRow | None:
    row = run_single(
        """
        MATCH (u:User {id: $user_id})-[:OWNS_TEMPLATE]->(t:ProceduralTemplate {id: $id})
        RETURN t {.*} AS template
        """,
        user_id=str(userId),
        id=templateId,
    )
    if row is None:
        return None
    template = TemplateRow(row["template"])
    actionsJson = template.get("actions_json")
    try:
        template["actions"] = json.loads(actionsJson) if actionsJson else []
    except (TypeError, ValueError):
        template["actions"] = []
    template.pop("actions_json", None)
    template["embedding"] = _deserializeEmbedding(template.get("embedding"))
    return template


def markTemplateStale(userId: str, templateId: str, *, reason: str = "") -> None:
    run_query(
        """
        MATCH (u:User {id: $user_id})-[:OWNS_TEMPLATE]->(t:ProceduralTemplate {id: $id})
        SET t.stale = true, t.staleness_reason = $reason, t.updated_at = $now
        """,
        user_id=str(userId),
        id=templateId,
        reason=reason,
        now=_nowIso(),
    )


def linkSupersedure(
    userId: str,
    *,
    fromTemplateId: str,
    toTemplateId: str,
    reason: str,
) -> None:
    run_query(
        """
        MATCH (u:User {id: $user_id})-[:OWNS_TEMPLATE]->(prev:ProceduralTemplate {id: $from_id})
        MATCH (u)-[:OWNS_TEMPLATE]->(next:ProceduralTemplate {id: $to_id})
        MERGE (prev)-[:SUPERSEDED_BY {reason: $reason, at: $at}]->(next)
        """,
        user_id=str(userId),
        from_id=fromTemplateId,
        to_id=toTemplateId,
        reason=reason,
        at=_nowIso(),
    )


def memoryDashboardStats(userId: str) -> dict[str, Any]:
    row = run_single(
        """
        MATCH (u:User {id: $user_id})
        OPTIONAL MATCH (u)-[:HOLDS]->(b:MemoryBullet)
        OPTIONAL MATCH (u)-[:OWNS_TEMPLATE]->(t:ProceduralTemplate)
        RETURN count(DISTINCT b) AS bullet_count,
               count(DISTINCT t) AS template_count,
               coalesce(sum(b.helpful_count), 0) AS total_helpful,
               coalesce(sum(b.harmful_count), 0) AS total_harmful
        """,
        user_id=str(userId),
    )
    if row is None:
        return {"bullet_count": 0, "template_count": 0, "total_helpful": 0, "total_harmful": 0}
    return {
        "bullet_count": int(row["bullet_count"]),
        "template_count": int(row["template_count"]),
        "total_helpful": int(row["total_helpful"]),
        "total_harmful": int(row["total_harmful"]),
    }
