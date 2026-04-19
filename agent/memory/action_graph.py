"""ActionNode + :NEXT edge graph schema for procedural memory.

Phase 2 of the miramemoria-parity plan. Represents a learned procedure
as a chain of `ActionNode`s connected by `:NEXT` edges, instead of as a
flat list of `:Bullet`s. Enables subgraph matching for partial replay.

Example: the task "make column C the sum of A and B in Sheets" might be
stored as:

    (n1:ActionNode {action_type:"navigate", target:"https://docs.google.com/..."})
        -[:NEXT]->
    (n2:ActionNode {action_type:"click_at", coord_x:384, coord_y:120, hash:"locate-col-C"})
        -[:NEXT]->
    (n3:ActionNode {action_type:"type_at", value:"=SUM(A:B)", coord_x:384, coord_y:140, hash:"set-formula"})

If a future task's decomposition matches n1→n2 verbatim, the runner
replays those nodes at zero cost and only invokes the model for n3 (or
whatever the new variant looks like).

The `hash` field is a content fingerprint — `(action_type, target,
canonical_value, coord_band)` — used as the equality key for subgraph
matching. Two ActionNodes with the same hash are considered identical
even if other fields (timestamps, run_id) differ.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ActionNode:
    """One step in a learned procedure.

    Mirrors the on-disk Cypher node shape so this dataclass can be used
    both for construction (post-decomposition) and inspection (post-load).

    State-verification fields (Phase 4): `expected_url` + `expected_phash`
    are recorded at save time from the actual run that produced this
    node. At replay time, `StateVerifier` compares them against the
    current page state to decide whether replay is safe.
    """
    id: str = field(default_factory = lambda: str(uuid.uuid4()))
    action_type: str = ""
    target: str = ""
    value: str = ""
    coord_x: int | None = None
    coord_y: int | None = None
    description: str = ""                  # human-readable label, e.g. "click formula bar"
    hash: str = ""                         # content fingerprint for subgraph match
    expected_url: str = ""                 # state at recording time (host + first path seg)
    expected_phash: str = ""               # 8x8 aHash of the screenshot at recording time
    metadata: dict[str, Any] = field(default_factory = dict)

    def __post_init__(self) -> None:
        if not self.hash:
            self.hash = computeActionHash(
                actionType = self.action_type,
                target = self.target,
                value = self.value,
                coordX = self.coord_x,
                coordY = self.coord_y,
            )


@dataclass
class ActionEdge:
    """A `:NEXT` edge between two ActionNodes within a procedure."""
    source_id: str
    target_id: str
    procedure_id: str                       # groups edges into a coherent procedure
    sequence_index: int = 0


@dataclass
class ProcedureGraph:
    """One procedure's nodes + edges, ready for persistence or replay."""
    procedure_id: str
    user_id: str
    task_description: str
    nodes: list[ActionNode] = field(default_factory = list)
    edges: list[ActionEdge] = field(default_factory = list)
    metadata: dict[str, Any] = field(default_factory = dict)

    def hashes(self) -> list[str]:
        """Ordered list of node hashes — the fingerprint for subgraph match."""
        return [n.hash for n in self.nodes]


def computeActionHash(
    *,
    actionType: str,
    target: str,
    value: str,
    coordX: int | None,
    coordY: int | None,
    coordBandPx: int = 16,
) -> str:
    """Content-fingerprint two ActionNodes are 'the same' if their hashes match.

    Coordinate bands quantize raw pixel positions into ~16px buckets so
    a click at (384, 120) and a click at (390, 122) on the same target
    page count as the same node — within Playwright's hit-test tolerance.
    """
    canonicalTarget = _canonicalize(target)
    canonicalValue = _canonicalize(value)
    bandX = coordX // coordBandPx if coordX is not None else None
    bandY = coordY // coordBandPx if coordY is not None else None
    parts = (
        actionType.lower(),
        canonicalTarget,
        canonicalValue,
        str(bandX) if bandX is not None else "_",
        str(bandY) if bandY is not None else "_",
    )
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _canonicalize(text: str) -> str:
    """Normalize whitespace + lowercase for stable comparison."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


class ActionGraphStore(Protocol):
    """Pluggable persistence Protocol for ActionGraphs.

    Implement against any backend (Neo4j is the canonical CUTIEE choice
    via apps/memory_app/action_graph_store.py). The library doesn't
    require a specific persistence layer.
    """
    def saveGraph(self, graph: ProcedureGraph) -> None: ...
    def loadGraphsForUser(self, userId: str, limit: int = 100) -> list[ProcedureGraph]: ...
    def loadGraphsByTopic(self, userId: str, topicSlug: str, limit: int = 10) -> list[ProcedureGraph]: ...


@dataclass
class InMemoryActionGraphStore:
    """In-process store for tests and standalone use."""
    graphs: dict[str, ProcedureGraph] = field(default_factory = dict)

    def saveGraph(self, graph: ProcedureGraph) -> None:
        self.graphs[graph.procedure_id] = graph

    def loadGraphsForUser(self, userId: str, limit: int = 100) -> list[ProcedureGraph]:
        out = [g for g in self.graphs.values() if g.user_id == userId]
        return out[:limit]

    def loadGraphsByTopic(self, userId: str, topicSlug: str, limit: int = 10) -> list[ProcedureGraph]:
        out = [
            g for g in self.graphs.values()
            if g.user_id == userId and g.metadata.get("topic_slug") == topicSlug
        ]
        return out[:limit]
