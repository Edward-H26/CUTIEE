"""Tests for ActionNode hashing + InMemoryActionGraphStore + SubgraphMatcher.

The hash is the foundation for subgraph matching: two nodes with the
same `(action_type, target, value, coord_band)` are considered the
"same" step regardless of timestamps or ids.
"""

from __future__ import annotations

from agent.memory.action_graph import (
    ActionNode,
    InMemoryActionGraphStore,
    ProcedureGraph,
    computeActionHash,
)
from agent.memory.subgraph_match import SubgraphMatcher


def _node(
    actionType: str, target: str = "", value: str = "", coord: tuple[int, int] | None = None
) -> ActionNode:
    return ActionNode(
        action_type=actionType,
        target=target,
        value=value,
        coord_x=coord[0] if coord else None,
        coord_y=coord[1] if coord else None,
    )


def test_hash_is_stable_across_construction() -> None:
    a = _node("click_at", coord=(100, 200))
    b = _node("click_at", coord=(100, 200))
    assert a.hash == b.hash


def test_hash_quantizes_pixel_coords_into_bands() -> None:
    """A click at (100,200) and (108,205) should hash the same (within 16px band)."""
    a = _node("click_at", coord=(100, 200))
    b = _node("click_at", coord=(108, 205))
    assert a.hash == b.hash


def test_hash_distinguishes_distant_coords() -> None:
    a = _node("click_at", coord=(100, 200))
    b = _node("click_at", coord=(500, 200))
    assert a.hash != b.hash


def test_hash_distinguishes_action_types() -> None:
    a = _node("click_at", coord=(100, 200))
    b = _node("type_at", coord=(100, 200))
    assert a.hash != b.hash


def test_hash_normalizes_whitespace_in_target() -> None:
    a = _node("navigate", target="  https://example.com  ")
    b = _node("navigate", target="https://example.com")
    assert a.hash == b.hash


def test_in_memory_store_round_trip() -> None:
    store = InMemoryActionGraphStore()
    g = ProcedureGraph(
        procedure_id="p1",
        user_id="alice",
        task_description="test task",
        nodes=[_node("navigate", target="https://x.com")],
    )
    store.saveGraph(g)
    loaded = store.loadGraphsForUser("alice")
    assert len(loaded) == 1
    assert loaded[0].procedure_id == "p1"


def test_procedure_graph_get_absolute_url() -> None:
    graph = ProcedureGraph(
        procedure_id="procedure-123",
        user_id="alice",
        task_description="test task",
    )

    assert graph.get_absolute_url() == "/memory/#procedure-procedure-123"


def test_subgraph_matcher_finds_full_prefix() -> None:
    """If the new task fully matches a stored procedure, all nodes are matched."""
    storedNodes = [
        _node("navigate", target="https://sheets.com"),
        _node("click_at", coord=(100, 200)),
        _node("type_at", value="=SUM(A:B)"),
    ]
    stored = ProcedureGraph(
        procedure_id="p1",
        user_id="alice",
        task_description="sheet sum",
        nodes=storedNodes,
    )
    newNodes = [
        _node("navigate", target="https://sheets.com"),
        _node("click_at", coord=(100, 200)),
        _node("type_at", value="=SUM(A:B)"),
    ]
    newTask = ProcedureGraph(
        procedure_id="p2",
        user_id="alice",
        task_description="sheet sum again",
        nodes=newNodes,
    )

    matcher = SubgraphMatcher()
    match = matcher.findBestMatch(newTask=newTask, storedGraphs=[stored])
    assert match is not None
    assert match.matchedLength == 3
    assert match.unmatchedSuffixLength == 0
    assert match.coverageRatio == 1.0


def test_subgraph_matcher_finds_partial_prefix() -> None:
    """The new task matches the first 2 of 3 stored nodes."""
    stored = ProcedureGraph(
        procedure_id="p1",
        user_id="alice",
        task_description="old",
        nodes=[
            _node("navigate", target="https://x.com"),
            _node("click_at", coord=(100, 200)),
            _node("type_at", value="old value"),
        ],
    )
    newTask = ProcedureGraph(
        procedure_id="p2",
        user_id="alice",
        task_description="new",
        nodes=[
            _node("navigate", target="https://x.com"),
            _node("click_at", coord=(100, 200)),
            _node("type_at", value="different value"),
        ],
    )
    matcher = SubgraphMatcher()
    match = matcher.findBestMatch(newTask=newTask, storedGraphs=[stored])
    assert match is not None
    assert match.matchedLength == 2
    assert match.unmatchedSuffixLength == 1


def test_subgraph_matcher_returns_none_when_no_match() -> None:
    stored = ProcedureGraph(
        procedure_id="p1",
        user_id="alice",
        task_description="old",
        nodes=[_node("navigate", target="https://x.com")],
    )
    newTask = ProcedureGraph(
        procedure_id="p2",
        user_id="alice",
        task_description="new",
        nodes=[_node("navigate", target="https://y.com")],
    )
    matcher = SubgraphMatcher(minPrefixLength=1)
    match = matcher.findBestMatch(newTask=newTask, storedGraphs=[stored])
    assert match is None


def test_subgraph_matcher_picks_longest_match_across_multiple_stored() -> None:
    stored1 = ProcedureGraph(
        procedure_id="p1",
        user_id="alice",
        task_description="short",
        nodes=[_node("navigate", target="https://x.com")],
    )
    stored2 = ProcedureGraph(
        procedure_id="p2",
        user_id="alice",
        task_description="long",
        nodes=[
            _node("navigate", target="https://x.com"),
            _node("click_at", coord=(10, 10)),
            _node("type_at", value="hello"),
        ],
    )
    newTask = ProcedureGraph(
        procedure_id="p3",
        user_id="alice",
        task_description="task",
        nodes=[
            _node("navigate", target="https://x.com"),
            _node("click_at", coord=(10, 10)),
            _node("type_at", value="hello"),
            _node("finish"),
        ],
    )
    matcher = SubgraphMatcher()
    match = matcher.findBestMatch(newTask=newTask, storedGraphs=[stored1, stored2])
    assert match is not None
    assert match.storedProcedureId == "p2"  # longer match wins
    assert match.matchedLength == 3


def test_compute_action_hash_handles_none_coords() -> None:
    """Non-coordinate actions (navigate, type_at without coord) should hash cleanly."""
    h = computeActionHash(
        actionType="navigate",
        target="https://x.com",
        value="",
        coordX=None,
        coordY=None,
    )
    assert isinstance(h, str)
    assert len(h) == 16
