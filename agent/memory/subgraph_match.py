"""Subgraph matcher — find the longest stored path that matches a new task.

Phase 3 of the miramemoria-parity plan. Given a new task's
`ProcedureGraph` decomposition and a collection of stored
`ProcedureGraph`s for the same user, returns the longest stored prefix
whose hashes match the new task's hashes.

The matched prefix can be REPLAYED at zero cost; only the unmatched
suffix needs to be sent to Computer Use. This is the partial-replay
upgrade over the current whole-template-or-nothing replay.

Algorithm: simple longest-common-prefix on the hash sequences. Not graph
isomorphism — that's overkill for the linear procedures we're storing.
If branching becomes important later, swap in NetworkX's VF2 isomorphism.

Match shape:

    Stored:    h1 → h2 → h3 → h4 → h5
    New task:  h1 → h2 → h3 → hX → hY
                    ^-- matched prefix (length 3)
                              ^-- unmatched suffix (length 2)

The runner replays h1, h2, h3 and only invokes the model for hX, hY.
"""
from __future__ import annotations

from dataclasses import dataclass

from .action_graph import ActionNode, ProcedureGraph


@dataclass
class SubgraphMatch:
    """Result of matching a new task against a stored procedure."""
    storedProcedureId: str
    matchedNodes: list[ActionNode]          # the prefix that matches (replayable)
    matchedLength: int                      # len(matchedNodes), surfaced for ranking
    newTaskTotalLength: int                 # so caller can compute coverage ratio
    unmatchedSuffixLength: int              # len(new task) - matchedLength

    @property
    def coverageRatio(self) -> float:
        if self.newTaskTotalLength == 0:
            return 0.0
        return self.matchedLength / self.newTaskTotalLength


@dataclass
class SubgraphMatcher:
    """Stateless matcher over a list of stored procedures.

    Parameters:
      minPrefixLength: skip matches shorter than this. Default 1, but
        callers usually want >= 2 to avoid trivial matches.
      requireFullMatch: if True, only return matches that cover the
        ENTIRE new task (equivalent to the existing whole-template replay).
    """
    minPrefixLength: int = 2
    requireFullMatch: bool = False

    def findBestMatch(
        self,
        *,
        newTask: ProcedureGraph,
        storedGraphs: list[ProcedureGraph],
    ) -> SubgraphMatch | None:
        """Return the stored graph with the longest matching prefix, or None."""
        if not newTask.nodes or not storedGraphs:
            return None
        newHashes = newTask.hashes()
        best: SubgraphMatch | None = None

        for stored in storedGraphs:
            storedHashes = stored.hashes()
            prefix = _longestCommonPrefix(newHashes, storedHashes)
            if prefix < self.minPrefixLength:
                continue
            if self.requireFullMatch and prefix != len(newHashes):
                continue
            match = SubgraphMatch(
                storedProcedureId = stored.procedure_id,
                matchedNodes = stored.nodes[:prefix],
                matchedLength = prefix,
                newTaskTotalLength = len(newHashes),
                unmatchedSuffixLength = len(newHashes) - prefix,
            )
            if best is None or match.matchedLength > best.matchedLength:
                best = match

        return best


def _longestCommonPrefix(seqA: list[str], seqB: list[str]) -> int:
    """How many leading elements are equal?"""
    n = 0
    for a, b in zip(seqA, seqB):
        if a == b:
            n += 1
        else:
            break
    return n


@dataclass
class ReusableStep:
    """One step in the new task that has a verbatim match somewhere in storage.

    `safeToReplay` is the conservative flag: True only when this step
    forms a contiguous prefix from position 0 in the new task. Out-of-prefix
    matches are returned for telemetry but not auto-executed because the
    page state may diverge from what the stored node expects.
    """
    newTaskIndex: int
    matchedNode: ActionNode
    sourceProcedureId: str
    safeToReplay: bool


def findReusableSteps(
    *,
    newTask: ProcedureGraph,
    storedGraphs: list[ProcedureGraph],
) -> list[ReusableStep]:
    """Per-step lookup across ALL stored graphs (not just one prefix match).

    Builds a hash → ActionNode index from every stored procedure, then
    walks the new task's nodes in order. For each new node:
      * If its hash is in the index, mark it as a `ReusableStep`.
      * `safeToReplay` is True only while we're still in a contiguous
        prefix from position 0. The first un-matched step closes the
        prefix; later matches still get reported (for observability)
        but with `safeToReplay=False`.

    Why the conservative replay rule: replaying a stored ActionNode at
    position N requires the page state at position N to match what the
    stored node expects. That holds for the prefix-from-zero case
    (every preceding step also replayed a stored node) but breaks once
    a fresh model call inserts an unexpected state in the middle.
    """
    if not newTask.nodes or not storedGraphs:
        return []

    # Index every stored ActionNode by its hash. Same hash from
    # different procedures → just keeps the first; the source procedure
    # id is reported so callers can pick a different one if they want.
    hashIndex: dict[str, tuple[ActionNode, str]] = {}
    for stored in storedGraphs:
        for node in stored.nodes:
            if node.hash and node.hash not in hashIndex:
                hashIndex[node.hash] = (node, stored.procedure_id)

    out: list[ReusableStep] = []
    inPrefix = True
    for i, newNode in enumerate(newTask.nodes):
        if not newNode.hash:
            inPrefix = False
            continue
        match = hashIndex.get(newNode.hash)
        if match is None:
            inPrefix = False
            continue
        matchedNode, procId = match
        out.append(ReusableStep(
            newTaskIndex = i,
            matchedNode = matchedNode,
            sourceProcedureId = procId,
            safeToReplay = inPrefix,
        ))

    return out


def reusableCoverageReport(steps: list[ReusableStep], totalSteps: int) -> dict:
    """Telemetry summary suitable for logging or dashboard display."""
    if totalSteps == 0:
        return {"total_steps": 0, "matched": 0, "safe_to_replay": 0, "coverage": 0.0}
    safeReplay = sum(1 for s in steps if s.safeToReplay)
    return {
        "total_steps": totalSteps,
        "matched": len(steps),
        "safe_to_replay": safeReplay,
        "coverage": len(steps) / totalSteps,
        "safe_replay_coverage": safeReplay / totalSteps,
    }
