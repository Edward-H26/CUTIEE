"""CUTIEE agent package — public surface (Computer Use only).

Importable as a standalone library; nothing in `agent/` depends on
Django, allauth, Neo4j, or any specific persistence layer. Implementations
of `BulletStore`, the audit sink, and the progress callback are injected
by the consumer (Django for the bundled web app, but anything else
can inject its own).

The legacy DOM-router stack (AdaptiveRouter / GeminiCloudClient / DOMState
extraction / RecencyPruner / Orchestrator) was removed once Gemini Flash
gained the ComputerUse tool at flash pricing. Every task now runs through
`ComputerUseRunner` with screenshot+pixel input.

Quick start:

    from agent import (
        ComputerUseRunner,
        buildComputerUseRunner,
        ACEMemory,
        InMemoryBulletStore,
        BrowserController,
        browserFromEnv,
        MockComputerUseClient,
    )
"""
from agent.browser.controller import (
    BrowserController,
    StepResult,
    StubBrowserController,
    browserFromEnv,
)
from agent.harness.computer_use_loop import ComputerUseRunner, buildComputerUseRunner
from agent.harness.config import Config
from agent.harness.env_utils import envBool, envFloat, envInt, envStr
from agent.harness.state import (
    Action,
    ActionType,
    AgentState,
    ObservationStep,
    RiskLevel,
)
from agent.memory.ace_memory import ACEMemory
from agent.memory.bullet import (
    MEMORY_TYPES,
    TYPE_PRIORITY,
    Bullet,
    DeltaUpdate,
    hashContent,
)
from agent.memory.curator import Curator
from agent.memory.decay import (
    EPISODIC_DECAY_RATE,
    PROCEDURAL_DECAY_RATE,
    SEMANTIC_DECAY_RATE,
    decayedStrength,
    totalDecayedStrength,
)
from agent.memory.pipeline import ACEPipeline, PipelineResult
from agent.memory.quality_gate import QualityGate, QualityGateDiagnostics
from agent.memory.reflector import HeuristicReflector, LessonCandidate
from agent.memory.replay import ReplayPlan, ReplayPlanner
from agent.memory.semantic import SemanticCredentialStore
from agent.memory.store import BulletStore, InMemoryBulletStore
from agent.routing.models.gemini_cu import (
    ComputerUseStep,
    GeminiComputerUseClient,
    MockComputerUseClient,
)
from agent.safety.approval_gate import ApprovalGate, ApprovalRequest
from agent.safety.audit import AuditPayload, buildAuditPayload
from agent.safety.risk_classifier import classifyRisk

__all__ = [
    "BrowserController", "StubBrowserController", "StepResult", "browserFromEnv",
    "Action", "ActionType", "AgentState", "ObservationStep", "RiskLevel",
    "Config",
    "envBool", "envFloat", "envInt", "envStr",
    "ComputerUseRunner", "buildComputerUseRunner",
    "ComputerUseStep", "GeminiComputerUseClient", "MockComputerUseClient",
    "Bullet", "DeltaUpdate", "MEMORY_TYPES", "TYPE_PRIORITY", "hashContent",
    "ACEMemory", "ACEPipeline", "PipelineResult",
    "BulletStore", "InMemoryBulletStore",
    "Curator", "QualityGate", "QualityGateDiagnostics",
    "HeuristicReflector", "LessonCandidate",
    "ReplayPlan", "ReplayPlanner",
    "SemanticCredentialStore",
    "EPISODIC_DECAY_RATE", "PROCEDURAL_DECAY_RATE", "SEMANTIC_DECAY_RATE",
    "decayedStrength", "totalDecayedStrength",
    "ApprovalGate", "ApprovalRequest",
    "AuditPayload", "buildAuditPayload",
    "classifyRisk",
]
