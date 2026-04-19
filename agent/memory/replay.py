"""Procedural replay — execute a workflow at zero inference cost.

The replay planner inspects the bullet store for procedural-type bullets
sharing the current task's `topic`. When the bullets cluster well above the
template-match threshold, the planner reconstructs an ordered list of
`Action` instances and the orchestrator runs them directly through the
browser controller. The first failed verification falls back to the router,
which produces a replacement procedural bullet via `DeltaUpdate`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent.harness.state import Action, ActionType, RiskLevel
from agent.memory.embeddings import cosineSimilarity, embedTexts
from agent.memory.pipeline import ACEPipeline
from agent.memory.bullet import Bullet


@dataclass
class ReplayPlan:
    topic: str
    bullets: list[Bullet] = field(default_factory = list)
    actions: list[Action] = field(default_factory = list)
    score: float = 0.0


@dataclass
class ReplayPlanner:
    pipeline: ACEPipeline
    matchThreshold: float = 0.85
    maxActions: int = 25

    async def findReplayPlan(self, taskDescription: str, userId: str) -> ReplayPlan | None:
        del userId  # ACEMemory inside the pipeline is already user-scoped.
        candidates = self.pipeline.retrieveRelevantBullets(taskDescription, k = 24)
        procedural = [b for b in candidates if b.memory_type == "procedural"]
        if not procedural:
            return None

        topicScores: dict[str, float] = {}
        topicBullets: dict[str, list[Bullet]] = {}
        queryEmbedding = embedTexts([taskDescription], useHashFallback = self.pipeline.memory.useHashEmbedding)[0]

        for bullet in procedural:
            if not bullet.topic:
                continue
            similarity = cosineSimilarity(queryEmbedding, bullet.embedding)
            topicScores[bullet.topic] = topicScores.get(bullet.topic, 0.0) + max(0.0, similarity)
            topicBullets.setdefault(bullet.topic, []).append(bullet)

        if not topicScores:
            return None

        bestTopic = max(topicScores, key = lambda t: topicScores[t])
        bestScore = topicScores[bestTopic]
        if bestScore < self.matchThreshold:
            return None

        bullets = topicBullets[bestTopic]
        bullets.sort(key = _stepIndexFromContent)
        actions = [_actionFromBullet(b) for b in bullets[: self.maxActions]]
        actions = [a for a in actions if a is not None]
        if not actions:
            return None
        return ReplayPlan(topic = bestTopic, bullets = bullets, actions = actions, score = bestScore)


def _stepIndexFromContent(bullet: Bullet) -> int:
    match = re.search(r"step_index=(\d+)", bullet.content)
    if match is None:
        return 0
    return int(match.group(1))


def _actionFromBullet(bullet: Bullet) -> Action | None:
    actionMatch = re.search(r"action=(\w+)", bullet.content)
    targetMatch = re.search(r"target='([^']*)'", bullet.content) or re.search(r'target="([^"]*)"', bullet.content)
    valueMatch = re.search(r"value='([^']*)'", bullet.content) or re.search(r'value="([^"]*)"', bullet.content)
    coordMatch = re.search(r"coordinate=\((-?\d+),(-?\d+)\)", bullet.content)
    keysMatch = re.search(r"keys=([\w+,\-]+)", bullet.content)
    scrollMatch = re.search(r"scroll=\((-?\d+),(-?\d+)\)", bullet.content)
    if actionMatch is None:
        return None
    try:
        actionType = ActionType(actionMatch.group(1))
    except ValueError:
        return None
    target = targetMatch.group(1) if targetMatch else ""
    value = valueMatch.group(1) if valueMatch else None
    coordinate = (int(coordMatch.group(1)), int(coordMatch.group(2))) if coordMatch else None
    keys = keysMatch.group(1).split(",") if keysMatch else None
    scrollDx = int(scrollMatch.group(1)) if scrollMatch else 0
    scrollDy = int(scrollMatch.group(2)) if scrollMatch else 0
    requiresApproval = "risk:high" in bullet.tags
    risk = RiskLevel.HIGH if requiresApproval else RiskLevel.LOW
    # CU bullets get tier=4 on replay so the audit log distinguishes
    # replayed-from-CU steps from replayed-from-DOM steps; cost stays $0
    # either way because no model call is made.
    isCu = "tier:cu" in bullet.tags or coordinate is not None
    return Action(
        type = actionType,
        target = target,
        value = value,
        coordinate = coordinate,
        keys = keys,
        scrollDx = scrollDx,
        scrollDy = scrollDy,
        reasoning = f"replay:{bullet.id[:8]}",
        model_used = "replay-cu" if isCu else "replay",
        tier = 4 if isCu else 0,
        confidence = 1.0,
        risk = risk,
        cost_usd = 0.0,
        requires_approval = requiresApproval,
    )


def replacementBulletFor(failedBullet: Bullet, replacementContent: str) -> dict[str, Any]:
    return {
        "failed_id": failedBullet.id,
        "patch": {
            "harmful_count": failedBullet.harmful_count + 1,
            "procedural_strength": max(0.0, failedBullet.procedural_strength - 1.0),
        },
        "replacement_content": replacementContent,
    }
