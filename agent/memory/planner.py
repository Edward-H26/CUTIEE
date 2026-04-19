"""Epsilon-greedy + UCB bandit planner — ported from miramemoria.

Picks one of N action levels (e.g., direct / explore / refine / deep_refine)
per task, and learns from the outcome via reward feedback. The choice is
explore vs exploit: with probability `epsilon` pick a random action;
otherwise pick the action with the highest `mean_reward + ucb_bonus`.

Self-contained — no LLM call. State is a small JSON-serializable dict
that lives on the parent `ACEMemory` (one bandit per user).

Usage:

    planner = Planner(memory=ace_memory)
    actionId = planner.chooseAction(
        featureText=task.description,
        actions=("direct", "explore", "refine", "deep_refine"),
    )
    # ... run the agent with that strategy ...
    planner.updateReward(actionId, reward=score, confidence=0.8)

For Computer Use specifically, the actions could be:
    ("single_shot", "explore_2", "refine_with_replay", "deep_refine_3pass")

For chat agents (miramemoria's setup):
    ("direct", "explore", "refine", "deep_refine")
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from .ace_memory import ACEMemory

DEFAULT_EPSILON = 0.1
DEFAULT_UCB_C = 1.4
DEFAULT_SEED = 42


@dataclass
class Planner:
    """Bandit planner stored as `plannerState` on an `ACEMemory`.

    Default policy: epsilon-greedy with UCB1 exploration bonus.
    Stats kept per action: `{pulls, updates, reward_sum}`.
    """
    memory: ACEMemory
    epsilon: float = DEFAULT_EPSILON
    ucbC: float = DEFAULT_UCB_C
    seed: int = DEFAULT_SEED

    def chooseAction(
        self,
        *,
        featureText: str = "",
        actions: tuple[str, ...] = ("single_shot",),
    ) -> str:
        """Pick the next action and bump its `pulls` count.

        `featureText` only seeds the RNG (so similar tasks get reproducible
        randomness). Doesn't influence the bandit's mean estimates — that's
        by design; the bandit learns from REWARDS, not from text features.
        """
        plannerState = dict(self.memory.plannerState or {})
        actionStats = plannerState.get("actions", {})
        totalPulls = int(plannerState.get("total_pulls", 0))
        rng = random.Random(int(self.seed) + self.memory.accessClock + len(featureText or ""))

        # Initialize stats for any newly-seen action
        for action in actions:
            actionStats.setdefault(action, {"pulls": 0, "updates": 0, "reward_sum": 0.0})

        explore = rng.random() < float(self.epsilon)
        scores = {}
        for action, stats in actionStats.items():
            if action not in actions:
                # Drop stats for actions we no longer support, but keep them
                # in plannerState in case they come back.
                continue
            pulls = int(stats.get("pulls", 0))
            updates = int(stats.get("updates", 0))
            rewardSum = float(stats.get("reward_sum", 0.0))
            mean = rewardSum / updates if updates > 0 else 0.5
            bonus = float(self.ucbC) * math.sqrt(
                math.log(totalPulls + len(actions) + 1) / (pulls + 1)
            )
            scores[action] = mean + bonus

        if explore:
            actionId = rng.choice(list(actions))
        else:
            # Sort descending; tie-break by name for determinism
            actionId = sorted(scores.keys(), key=lambda k: (scores[k], k), reverse=True)[0]

        actionStats[actionId]["pulls"] = int(actionStats[actionId].get("pulls", 0)) + 1
        plannerState["actions"] = actionStats
        plannerState["total_pulls"] = totalPulls + 1
        self.memory.plannerState = plannerState
        return actionId

    def updateReward(
        self,
        actionId: str,
        *,
        reward: float,
        confidence: float = 1.0,
    ) -> None:
        """Record reward for a completed action.

        `confidence` weights the reward — a confident success is a stronger
        signal than an uncertain one. Matches miramemoria's
        `update_planner_reward(action_id, reward, confidence)`.
        """
        plannerState = dict(self.memory.plannerState or {})
        actionStats = plannerState.get("actions", {})
        stats = actionStats.get(actionId)
        if stats is None:
            stats = {"pulls": 0, "updates": 0, "reward_sum": 0.0}
        weightedReward = float(reward) * float(confidence)
        stats["updates"] = int(stats.get("updates", 0)) + 1
        stats["reward_sum"] = float(stats.get("reward_sum", 0.0)) + weightedReward
        actionStats[actionId] = stats
        plannerState["actions"] = actionStats
        plannerState["total_updates"] = int(plannerState.get("total_updates", 0)) + 1
        self.memory.plannerState = plannerState

    def stats(self) -> dict[str, Any]:
        """Snapshot current bandit state for inspection / dashboard."""
        plannerState = dict(self.memory.plannerState or {})
        actionStats = plannerState.get("actions", {})
        out = {"total_pulls": plannerState.get("total_pulls", 0), "actions": {}}
        for action, stats in actionStats.items():
            updates = int(stats.get("updates", 0))
            rewardSum = float(stats.get("reward_sum", 0.0))
            mean = rewardSum / updates if updates > 0 else 0.0
            out["actions"][action] = {
                "pulls": int(stats.get("pulls", 0)),
                "updates": updates,
                "mean_reward": round(mean, 4),
            }
        return out


# Default action sets for two common consumer scenarios.
CHAT_ACTIONS = ("direct", "explore", "refine", "deep_refine")
CU_ACTIONS = ("single_shot", "explore_2", "refine_with_replay")
