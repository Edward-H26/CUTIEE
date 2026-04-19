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
from .browser.controller import (
    BrowserController,
    StepResult,
    StubBrowserController,
    browserFromEnv,
)
from .harness.computer_use_loop import ComputerUseRunner, buildComputerUseRunner
from .harness.config import Config
from .harness.env_utils import envBool, envFloat, envInt, envStr
from .harness.state import (
    Action,
    ActionType,
    AgentState,
    ObservationStep,
    RiskLevel,
)
from .memory.ace_memory import ACEMemory
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
from .memory.pipeline import ACEPipeline, PipelineResult
from .memory.quality_gate import QualityGate, QualityGateDiagnostics
from .memory.reflector import HeuristicReflector, LessonCandidate
from .memory.replay import ReplayPlan, ReplayPlanner
from .memory.semantic import SemanticCredentialStore
from .memory.store import BulletStore, InMemoryBulletStore
from .routing.models.gemini_cu import (
    ComputerUseStep,
    GeminiComputerUseClient,
    MockComputerUseClient,
)
from .safety.approval_gate import ApprovalGate, ApprovalRequest
from .safety.audit import AuditPayload, buildAuditPayload
from .safety.risk_classifier import classifyRisk

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
