"""Tests for the per-step reuse lookup (findReusableSteps).

Validates the conservative safety semantic: only steps that form a
contiguous prefix from position 0 are flagged `safeToReplay=True`.
Out-of-prefix matches still get reported (for telemetry) but with
`safeToReplay=False` so the runner won't auto-replay them.
"""

from __future__ import annotations

from agent.memory.action_graph import ActionNode, ProcedureGraph
from agent.memory.subgraph_match import (
    findReusableSteps,
    reusableCoverageReport,
)


def _node(actionType: str, target: str = "", value: str = "", coord=None) -> ActionNode:
    return ActionNode(
        action_type=actionType,
        target=target,
        value=value,
        coord_x=coord[0] if coord else None,
        coord_y=coord[1] if coord else None,
    )


def test_per_step_lookup_finds_match_in_middle_of_stored_graph() -> None:
    """A new step matches a node sitting in the middle of an old procedure."""
    stored = ProcedureGraph(
        procedure_id="p1",
        user_id="alice",
        task_description="old",
        nodes=[
            _node("navigate", target="https://x.com"),
            _node("click_at", coord=(100, 200)),
            _node("type_at", value="hello"),
        ],
    )
    # New task starts with the SAME first step but then diverges,
    # eventually lining up again with the old type_at step.
    newTask = ProcedureGraph(
        procedure_id="p2",
        user_id="alice",
        task_description="new",
        nodes=[
            _node("navigate", target="https://x.com"),  # match (prefix)
            _node("click_at", coord=(500, 500)),  # no match
            _node("type_at", value="hello"),  # match (out of prefix)
        ],
    )
    reusable = findReusableSteps(newTask=newTask, storedGraphs=[stored])
    assert len(reusable) == 2

    # Step 0 matched + safe (in contiguous prefix from position 0)
    assert reusable[0].newTaskIndex == 0
    assert reusable[0].safeToReplay is True

    # Step 2 matched but NOT safe (out of prefix because step 1 broke it)
    assert reusable[1].newTaskIndex == 2
    assert reusable[1].safeToReplay is False


def test_per_step_lookup_aggregates_across_multiple_stored_graphs() -> None:
    """Steps can match nodes from different stored procedures."""
    storedA = ProcedureGraph(
        procedure_id="pA",
        user_id="alice",
        task_description="old A",
        nodes=[_node("navigate", target="https://x.com")],
    )
    storedB = ProcedureGraph(
        procedure_id="pB",
        user_id="alice",
        task_description="old B",
        nodes=[_node("type_at", value="hello")],
    )
    newTask = ProcedureGraph(
        procedure_id="p2",
        user_id="alice",
        task_description="new",
        nodes=[
            _node("navigate", target="https://x.com"),  # from pA
            _node("type_at", value="hello"),  # from pB
        ],
    )
    reusable = findReusableSteps(newTask=newTask, storedGraphs=[storedA, storedB])
    assert len(reusable) == 2
    assert {r.sourceProcedureId for r in reusable} == {"pA", "pB"}
    # Both are in contiguous prefix → both safe
    assert all(r.safeToReplay for r in reusable)


def test_coverage_report_summary() -> None:
    stored = ProcedureGraph(
        procedure_id="p1",
        user_id="alice",
        task_description="old",
        nodes=[
            _node("navigate", target="https://x.com"),
            _node("type_at", value="X"),
        ],
    )
    newTask = ProcedureGraph(
        procedure_id="p2",
        user_id="alice",
        task_description="new",
        nodes=[
            _node("navigate", target="https://x.com"),  # safe
            _node("click_at", coord=(1, 1)),  # no match
            _node("type_at", value="X"),  # match, not safe
            _node("scroll_at", coord=(0, 100)),  # no match
        ],
    )
    reusable = findReusableSteps(newTask=newTask, storedGraphs=[stored])
    report = reusableCoverageReport(reusable, len(newTask.nodes))
    assert report["total_steps"] == 4
    assert report["matched"] == 2  # 2 of 4 hit the index
    assert report["safe_to_replay"] == 1  # only the prefix one is safe
    assert report["coverage"] == 0.5
    assert report["safe_replay_coverage"] == 0.25


def test_no_stored_graphs_returns_empty() -> None:
    newTask = ProcedureGraph(
        procedure_id="p2",
        user_id="alice",
        task_description="new",
        nodes=[_node("navigate", target="https://x.com")],
    )
    reusable = findReusableSteps(newTask=newTask, storedGraphs=[])
    assert reusable == []


def test_empty_new_task_returns_empty() -> None:
    stored = ProcedureGraph(
        procedure_id="p1",
        user_id="alice",
        task_description="old",
        nodes=[_node("navigate", target="https://x.com")],
    )
    empty = ProcedureGraph(procedure_id="p2", user_id="alice", task_description="")
    reusable = findReusableSteps(newTask=empty, storedGraphs=[stored])
    assert reusable == []


def test_first_match_wins_when_same_hash_in_multiple_procedures() -> None:
    """If hash X appears in 2 stored procedures, the first one indexed wins."""
    storedA = ProcedureGraph(
        procedure_id="pA",
        user_id="alice",
        task_description="A",
        nodes=[_node("navigate", target="https://shared.com")],
    )
    storedB = ProcedureGraph(
        procedure_id="pB",
        user_id="alice",
        task_description="B",
        nodes=[_node("navigate", target="https://shared.com")],
    )
    newTask = ProcedureGraph(
        procedure_id="p2",
        user_id="alice",
        task_description="n",
        nodes=[_node("navigate", target="https://shared.com")],
    )
    reusable = findReusableSteps(newTask=newTask, storedGraphs=[storedA, storedB])
    assert len(reusable) == 1
    assert reusable[0].sourceProcedureId == "pA"
