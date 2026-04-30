"""CUTIEE agent package, the public surface for Computer Use workflows.

Importable as a standalone library. Nothing in `agent/` depends on
Django, allauth, or any specific persistence layer; implementations
of `BulletStore`, the audit sink, and the progress callback are
injected by the consumer (Django for the bundled web app, any other
host for a custom integration).

Every task runs through a single agent loop, `ComputerUseRunner`,
which drives a screenshot to pixel-action cycle against a pluggable
`CuClient`. Two client implementations ship today: the default
`GeminiComputerUseClient` (flash-tier Gemini CU) and
`BrowserUseClient` (browser-use wrapping Gemini 3 Flash). Optional
safety and memory-hygiene collaborators (injection guard, CAPTCHA
detector, heartbeat, preview, fragment replay) plug in through
fields on the runner and are no-ops when absent.

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
from .memory.store import BulletStore, InMemoryBulletStore
from .routing.cu_client import ComputerUseStep, CuClient
from .routing.models.gemini_cu import (
    GeminiComputerUseClient,
    MockComputerUseClient,
)
from .safety.approval_gate import ApprovalGate, ApprovalRequest
from .safety.audit import AuditPayload, buildAuditPayload
from .safety.risk_classifier import classifyRisk

__all__ = [
    "BrowserController",
    "StubBrowserController",
    "StepResult",
    "browserFromEnv",
    "Action",
    "ActionType",
    "AgentState",
    "ObservationStep",
    "RiskLevel",
    "Config",
    "envBool",
    "envFloat",
    "envInt",
    "envStr",
    "ComputerUseRunner",
    "buildComputerUseRunner",
    "ComputerUseStep",
    "CuClient",
    "GeminiComputerUseClient",
    "MockComputerUseClient",
    "Bullet",
    "DeltaUpdate",
    "MEMORY_TYPES",
    "TYPE_PRIORITY",
    "hashContent",
    "ACEMemory",
    "ACEPipeline",
    "PipelineResult",
    "BulletStore",
    "InMemoryBulletStore",
    "Curator",
    "QualityGate",
    "QualityGateDiagnostics",
    "HeuristicReflector",
    "LessonCandidate",
    "ReplayPlan",
    "ReplayPlanner",
    "EPISODIC_DECAY_RATE",
    "PROCEDURAL_DECAY_RATE",
    "SEMANTIC_DECAY_RATE",
    "decayedStrength",
    "totalDecayedStrength",
    "ApprovalGate",
    "ApprovalRequest",
    "AuditPayload",
    "buildAuditPayload",
    "classifyRisk",
]
