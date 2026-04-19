"""cutiee-ace — self-evolving memory + temporal context pruning + procedural graph for LLM agents.

A standalone Python package extracted from CUTIEE. Brings the full
miramemoria-parity ACE pipeline plus four new layers built specifically
for browser-automation / Computer Use agents:

  1. **ACE memory framework**: three-strength bullets (semantic / episodic /
     procedural), per-channel exponential decay, retrieval ranking, and the
     self-evolving Reflector → QualityGate → Curator → Apply pipeline.

  2. **Procedural replay**: re-execute a memorized workflow at zero
     inference cost when the current task matches a stored template.

  3. **Temporal recency pruning**: bound prompt size while preserving the
     most-recent N steps verbatim and rolling up older history.

  4. **Procedural graph (Phase 2)**: store learned procedures as
     `ActionNode`s connected by `:NEXT` edges instead of flat bullets.
     Enables sub-graph matching for partial replay.

  5. **Bandit planner (Phase 3)**: epsilon-greedy + UCB1 over per-task
     strategies (single_shot / explore / refine / deep_refine).

  6. **State verification (Phase 4)**: URL + perceptual-hash check before
     replaying a stored ActionNode, so safer mid-task replay can be
     unlocked without the page-state-mismatch risk.

Quick start:

    from cutiee_ace import (
        ACEMemory, ACEPipeline, InMemoryBulletStore,
        Planner, CU_ACTIONS,
        ActionNode, ProcedureGraph, SubgraphMatcher, findReusableSteps,
        StateVerifier, computeAverageHash,
    )

    memory = ACEMemory(userId = "alice", store = InMemoryBulletStore())
    pipeline = ACEPipeline.fromEnv(memory = memory)         # CUTIEE_REFLECTOR=llm switches to Gemini
    pipeline.processExecution(my_agent_state)               # writes lessons learned

    planner = Planner(memory = memory)
    strategy = planner.chooseAction(actions = CU_ACTIONS)

Pluggable persistence: implement the `BulletStore` Protocol against any
backend (Postgres, Neo4j, Redis, in-memory) and inject it into ACEMemory.
"""
from .env_utils import envBool, envFloat, envInt, envStr
from .memory.ace_memory import ACEMemory
from .memory.action_graph import (
    ActionEdge,
    ActionGraphStore,
    ActionNode,
    InMemoryActionGraphStore,
    ProcedureGraph,
    computeActionHash,
)
from .memory.bullet import (
    MEMORY_TYPES,
    TYPE_PRIORITY,
    Bullet,
    DeltaUpdate,
    hashContent,
)
from .memory.curator import Curator
from .memory.decay import (
    EPISODIC_DECAY_RATE,
    PROCEDURAL_DECAY_RATE,
    SEMANTIC_DECAY_RATE,
    decayedStrength,
    totalDecayedStrength,
)
from .memory.decomposer import (
    DECOMPOSER_PROMPT,
    DECOMPOSER_SYSTEM_INSTRUCTION,
    LlmActionDecomposer,
)
from .memory.pipeline import ACEPipeline, PipelineResult
from .memory.planner import (
    CHAT_ACTIONS,
    CU_ACTIONS,
    DEFAULT_EPSILON,
    DEFAULT_UCB_C,
    Planner,
)
from .memory.quality_gate import QualityGate, QualityGateDiagnostics
from .memory.reflector import (
    HeuristicReflector,
    LessonCandidate,
    LlmReflector,
    REFLECTOR_PROMPT,
    REFLECTOR_SYSTEM_INSTRUCTION,
    Reflector,
    buildReflector,
)
from .memory.replay import ReplayPlan, ReplayPlanner
from .memory.semantic import SemanticCredentialStore
from .memory.state_verifier import (
    DEFAULT_PHASH_HAMMING_THRESHOLD,
    StateVerifier,
    VerificationResult,
    computeAverageHash,
    hammingDistance,
)
from .memory.store import BulletStore, InMemoryBulletStore
from .memory.subgraph_match import (
    ReusableStep,
    SubgraphMatch,
    SubgraphMatcher,
    findReusableSteps,
    reusableCoverageReport,
)
from .pruning import (
    PrunedContext,
    RecencyPruner,
    TokenBudget,
    allocateFgBgBudget,
    estimateTokens,
    ruleBasedSummary,
)
from .safety.audit import AuditPayload, buildAuditPayload
from .safety.risk_classifier import classifyRisk
from .state import Action, ActionType, AgentState, ObservationStep, RiskLevel

__version__ = "0.2.0"

__all__ = [
    # harness primitives
    "Action", "ActionType", "AgentState", "ObservationStep", "RiskLevel",
    "envBool", "envFloat", "envInt", "envStr",
    # ACE memory
    "ACEMemory", "ACEPipeline", "PipelineResult",
    "Bullet", "DeltaUpdate", "MEMORY_TYPES", "TYPE_PRIORITY", "hashContent",
    "BulletStore", "InMemoryBulletStore",
    "Curator", "QualityGate", "QualityGateDiagnostics",
    "HeuristicReflector", "LessonCandidate",
    "LlmReflector", "Reflector", "buildReflector",
    "REFLECTOR_PROMPT", "REFLECTOR_SYSTEM_INSTRUCTION",
    "ReplayPlan", "ReplayPlanner",
    "SemanticCredentialStore",
    "EPISODIC_DECAY_RATE", "PROCEDURAL_DECAY_RATE", "SEMANTIC_DECAY_RATE",
    "decayedStrength", "totalDecayedStrength",
    # Pruning
    "PrunedContext", "RecencyPruner",
    "TokenBudget", "allocateFgBgBudget", "estimateTokens", "ruleBasedSummary",
    # Procedural graph (Phase 2)
    "ActionEdge", "ActionGraphStore", "ActionNode", "InMemoryActionGraphStore",
    "ProcedureGraph", "computeActionHash",
    # Bandit planner (Phase 3)
    "CHAT_ACTIONS", "CU_ACTIONS", "DEFAULT_EPSILON", "DEFAULT_UCB_C", "Planner",
    # Subgraph matching + per-step reuse
    "ReusableStep", "SubgraphMatch", "SubgraphMatcher",
    "findReusableSteps", "reusableCoverageReport",
    # Decomposer (LLM-driven action chain extraction)
    "DECOMPOSER_PROMPT", "DECOMPOSER_SYSTEM_INSTRUCTION", "LlmActionDecomposer",
    # State verifier (Phase 4)
    "DEFAULT_PHASH_HAMMING_THRESHOLD", "StateVerifier", "VerificationResult",
    "computeAverageHash", "hammingDistance",
    # Safety
    "AuditPayload", "buildAuditPayload", "classifyRisk",
]
