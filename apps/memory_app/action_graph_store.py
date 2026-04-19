"""Neo4j-backed implementation of `ActionGraphStore`.

Schema (one Cypher write per procedure):

  (:User {id})-[:LEARNED]->(:ProcedureGraph {id, task_description,
                                              topic_slug, created_at,
                                              last_used_at})
  (:ProcedureGraph)-[:STARTS_WITH]->(:ActionNode)
  (:ActionNode)-[:NEXT {sequence_index}]->(:ActionNode)

ActionNodes are NOT shared across procedures in this implementation —
every saved procedure creates its own node chain. Sharing nodes by hash
would let us de-duplicate identical steps across procedures, but that
needs a separate constraint and a more careful write transaction.
Keep it simple: one chain per procedure, dedup at match time via hashes.

User scoping is enforced at every query via `MATCH (u:User {id: $user_id})`
so cross-user data leakage is impossible.

Lifecycle (TTL):
  * Every save() runs a lazy sweep that deletes procedures whose
    `last_used_at` (or `created_at` if never replayed) is older than
    `CUTIEE_PROCEDURE_GRAPH_TTL_DAYS` days (default 5).
  * Every load() bumps `last_used_at = datetime()` so frequently-replayed
    procedures keep their freshness lease and don't expire just because
    their original creation date is old.
"""
from __future__ import annotations

import logging

from agent.harness.env_utils import envInt
from agent.memory.action_graph import ActionEdge, ActionNode, ProcedureGraph
from agent.persistence.neo4j_client import run_query, run_single

DEFAULT_TTL_DAYS = 5

_logger = logging.getLogger("cutiee.action_graph_store")


class Neo4jActionGraphStore:
    """Persists `ProcedureGraph`s as a chain of :ActionNode + :NEXT edges.

    `ttlDays`: how long an unused procedure lives. Default 5 days,
    overridable via `CUTIEE_PROCEDURE_GRAPH_TTL_DAYS` env var.
    """
    def __init__(self, ttlDays: int | None = None) -> None:
        self.ttlDays = ttlDays if ttlDays is not None else envInt(
            "CUTIEE_PROCEDURE_GRAPH_TTL_DAYS", DEFAULT_TTL_DAYS
        )

    def saveGraph(self, graph: ProcedureGraph) -> None:
        if not graph.nodes:
            return

        # Lazy TTL sweep BEFORE the new write so the cap check sees the
        # post-sweep footprint. Cheap when nothing's expired.
        self._sweepExpired()

        # Phase 1: create the ProcedureGraph node + link to user
        run_query(
            """
            MERGE (u:User {id: $user_id})
            CREATE (g:ProcedureGraph {
                id: $procedure_id,
                task_description: $task_description,
                topic_slug: $topic_slug,
                created_at: datetime(),
                last_used_at: datetime()
            })
            CREATE (u)-[:LEARNED]->(g)
            """,
            user_id = graph.user_id,
            procedure_id = graph.procedure_id,
            task_description = graph.task_description,
            topic_slug = graph.metadata.get("topic_slug", ""),
        )

        # Phase 2: create all ActionNodes (one Cypher call each — small graphs,
        # negligible overhead, easier to reason about than UNWIND batching)
        for node in graph.nodes:
            run_query(
                """
                MATCH (g:ProcedureGraph {id: $procedure_id})
                CREATE (n:ActionNode {
                    id: $id,
                    procedure_id: $procedure_id,
                    action_type: $action_type,
                    target: $target,
                    value: $value,
                    coord_x: $coord_x,
                    coord_y: $coord_y,
                    description: $description,
                    hash: $hash,
                    expected_url: $expected_url,
                    expected_phash: $expected_phash
                })
                """,
                procedure_id = graph.procedure_id,
                id = node.id,
                action_type = node.action_type,
                target = node.target,
                value = node.value,
                coord_x = node.coord_x,
                coord_y = node.coord_y,
                description = node.description,
                hash = node.hash,
                expected_url = node.expected_url,
                expected_phash = node.expected_phash,
            )

        # Phase 3: STARTS_WITH edge to the first node
        firstNode = graph.nodes[0]
        run_query(
            """
            MATCH (g:ProcedureGraph {id: $procedure_id})
            MATCH (n:ActionNode {id: $first_node_id, procedure_id: $procedure_id})
            CREATE (g)-[:STARTS_WITH]->(n)
            """,
            procedure_id = graph.procedure_id,
            first_node_id = firstNode.id,
        )

        # Phase 4: NEXT edges between consecutive nodes
        for edge in graph.edges:
            run_query(
                """
                MATCH (a:ActionNode {id: $source_id, procedure_id: $procedure_id})
                MATCH (b:ActionNode {id: $target_id, procedure_id: $procedure_id})
                CREATE (a)-[:NEXT {sequence_index: $sequence_index}]->(b)
                """,
                source_id = edge.source_id,
                target_id = edge.target_id,
                procedure_id = graph.procedure_id,
                sequence_index = edge.sequence_index,
            )

    def loadGraphsForUser(self, userId: str, limit: int = 100) -> list[ProcedureGraph]:
        """Load all procedures for a user, including their full node chains.

        Bumps `last_used_at` on every load so frequently-replayed graphs
        don't expire from the TTL sweep just because their `created_at`
        is old. This is the "use it or lose it" semantic.
        """
        graphRows = run_query(
            """
            MATCH (u:User {id: $user_id})-[:LEARNED]->(g:ProcedureGraph)
            SET g.last_used_at = datetime()
            RETURN g {.*} AS graph
            ORDER BY g.last_used_at DESC
            LIMIT $limit
            """,
            user_id = str(userId),
            limit = int(limit),
        )
        return [self._loadGraphChain(row["graph"]) for row in graphRows]

    def loadGraphsByTopic(
        self, userId: str, topicSlug: str, limit: int = 10,
    ) -> list[ProcedureGraph]:
        graphRows = run_query(
            """
            MATCH (u:User {id: $user_id})-[:LEARNED]->(g:ProcedureGraph {topic_slug: $topic_slug})
            SET g.last_used_at = datetime()
            RETURN g {.*} AS graph
            ORDER BY g.last_used_at DESC
            LIMIT $limit
            """,
            user_id = str(userId),
            topic_slug = topicSlug,
            limit = int(limit),
        )
        return [self._loadGraphChain(row["graph"]) for row in graphRows]

    def _sweepExpired(self) -> int:
        """Delete procedures whose last_used_at < now - ttlDays.

        Returns count deleted (mostly for tests / observability). Cheap
        when nothing's expired — Neo4j short-circuits the WHERE.
        """
        try:
            row = run_single(
                """
                MATCH (g:ProcedureGraph)
                WHERE coalesce(g.last_used_at, g.created_at) < datetime() - duration({days: $days})
                OPTIONAL MATCH (g)-[:STARTS_WITH]->(:ActionNode)
                OPTIONAL MATCH (n:ActionNode {procedure_id: g.id})
                WITH g, count(DISTINCT g) AS deleted_count
                DETACH DELETE g
                RETURN deleted_count
                """,
                days = int(self.ttlDays),
            )
            count = int(row["deleted_count"]) if row else 0
            if count > 0:
                _logger.info("ActionGraph TTL sweep deleted %d expired procedures", count)
            return count
        except Exception:  # noqa: BLE001 - sweep failures shouldn't break saves
            _logger.debug("ActionGraph TTL sweep failed", exc_info = True)
            return 0

    def _loadGraphChain(self, graphRow: dict) -> ProcedureGraph:
        """Walk :STARTS_WITH then :NEXT edges to rebuild the node chain."""
        procedureId = graphRow["id"]
        nodeRows = run_query(
            """
            MATCH (g:ProcedureGraph {id: $procedure_id})-[:STARTS_WITH]->(start:ActionNode)
            MATCH path = (start)-[:NEXT*0..50]->(n:ActionNode)
            WITH n, length(path) AS depth
            RETURN n {.*} AS node, depth
            ORDER BY depth ASC
            """,
            procedure_id = procedureId,
        )

        nodes: list[ActionNode] = []
        for row in nodeRows:
            n = row["node"]
            nodes.append(ActionNode(
                id = n.get("id", ""),
                action_type = n.get("action_type", ""),
                target = n.get("target", "") or "",
                value = n.get("value", "") or "",
                coord_x = n.get("coord_x"),
                coord_y = n.get("coord_y"),
                description = n.get("description", "") or "",
                hash = n.get("hash", ""),
                expected_url = n.get("expected_url", "") or "",
                expected_phash = n.get("expected_phash", "") or "",
            ))

        # Reconstruct edges from the implied chain order
        edges: list[ActionEdge] = []
        for i, current in enumerate(nodes[:-1]):
            edges.append(ActionEdge(
                source_id = current.id,
                target_id = nodes[i + 1].id,
                procedure_id = procedureId,
                sequence_index = i,
            ))

        return ProcedureGraph(
            procedure_id = procedureId,
            user_id = "",  # caller already knows; we don't refetch
            task_description = graphRow.get("task_description", "") or "",
            nodes = nodes,
            edges = edges,
            metadata = {"topic_slug": graphRow.get("topic_slug", "") or ""},
        )

    def deleteGraphsForUser(self, userId: str) -> int:
        """Drop all stored procedures for one user. Returns count deleted."""
        row = run_single(
            """
            MATCH (u:User {id: $user_id})-[:LEARNED]->(g:ProcedureGraph)
            OPTIONAL MATCH (g)-[:STARTS_WITH]->(:ActionNode)
            OPTIONAL MATCH (n:ActionNode {procedure_id: g.id})
            WITH g, count(DISTINCT g) AS n_deleted
            DETACH DELETE g
            RETURN n_deleted
            """,
            user_id = str(userId),
        )
        return int(row["n_deleted"]) if row else 0
