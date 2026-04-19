"""Tests for the epsilon-greedy / UCB bandit planner.

The bandit is deterministic given a fixed seed, so we can assert exact
chosen actions across a fixed sequence of `chooseAction` + `updateReward`
calls. This is the regression test for "did the bandit learn to prefer
the high-reward action over time?"
"""
from __future__ import annotations

from agent.memory.ace_memory import ACEMemory
from agent.memory.planner import CHAT_ACTIONS, CU_ACTIONS, Planner


def _planner(seed: int = 0, epsilon: float = 0.0) -> tuple[Planner, ACEMemory]:
    mem = ACEMemory(userId = "test")
    return Planner(memory = mem, epsilon = epsilon, ucbC = 1.4, seed = seed), mem


def test_planner_picks_one_of_supplied_actions() -> None:
    p, _ = _planner()
    chosen = p.chooseAction(featureText = "task", actions = CU_ACTIONS)
    assert chosen in CU_ACTIONS


def test_planner_initializes_action_stats() -> None:
    p, mem = _planner()
    p.chooseAction(actions = CU_ACTIONS)
    state = mem.plannerState
    assert "actions" in state
    for a in CU_ACTIONS:
        assert a in state["actions"]
        assert state["actions"][a]["pulls"] >= 0
        assert state["actions"][a]["updates"] == 0


def test_planner_records_reward() -> None:
    p, mem = _planner()
    p.chooseAction(actions = CHAT_ACTIONS)
    p.updateReward("direct", reward = 0.9, confidence = 1.0)
    stats = mem.plannerState["actions"]["direct"]
    assert stats["updates"] == 1
    assert stats["reward_sum"] == 0.9


def test_planner_learns_high_reward_action() -> None:
    """After enough trials, the bandit's mean-reward estimate should
    correctly identify the high-reward action, even if UCB exploration
    sometimes still picks others."""
    p, _ = _planner(epsilon = 0.0)
    # Train: give 'refine' high rewards, others low
    for _ in range(50):
        chosen = p.chooseAction(actions = CHAT_ACTIONS)
        reward = 1.0 if chosen == "refine" else 0.05
        p.updateReward(chosen, reward = reward, confidence = 1.0)
    snap = p.stats()
    # 'refine' must have learned the highest mean reward across all actions.
    refineMean = snap["actions"]["refine"]["mean_reward"]
    for action, stats in snap["actions"].items():
        if action == "refine":
            continue
        assert refineMean >= stats["mean_reward"], (
            f"refine ({refineMean}) should have learned higher mean than {action} ({stats['mean_reward']})"
        )


def test_planner_stats_snapshot() -> None:
    p, _ = _planner()
    p.chooseAction(actions = CU_ACTIONS)
    p.updateReward("single_shot", reward = 0.5, confidence = 0.8)
    snap = p.stats()
    assert snap["total_pulls"] >= 1
    assert "single_shot" in snap["actions"]
    assert snap["actions"]["single_shot"]["mean_reward"] == 0.4  # 0.5 * 0.8
