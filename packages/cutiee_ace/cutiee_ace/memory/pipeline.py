"""Self-evolving pipeline orchestrating Reflector → QualityGate → Curator.

The pipeline is the single entry point the orchestrator calls after every
finished task. It owns the policy decisions (which reflector to use, which
gate threshold, whether to refine after applying the delta) so callers don't
have to know the internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from typing import Any

from ..state import AgentState
from .ace_memory import ACEMemory
from .curator import Curator
from .quality_gate import QualityGate, QualityGateDiagnostics
from .reflector import HeuristicReflector, Reflector, buildReflector
from .bullet import Bullet, DeltaUpdate


@dataclass
class PipelineResult:
    accepted: bool
    diagnostics: QualityGateDiagnostics
    delta: DeltaUpdate = field(default_factory = DeltaUpdate)
    refinedRemovals: int = 0


@dataclass
class ACEPipeline:
    memory: ACEMemory
    # `reflector` accepts anything implementing the Reflector Protocol —
    # `HeuristicReflector` (default), `LlmReflector`, or a custom one
    # (e.g., a CU-specific reflector that emits structured action graphs).
    # Use `buildReflector()` to pick based on `CUTIEE_REFLECTOR` env.
    reflector: Any = field(default_factory = HeuristicReflector)
    qualityGate: QualityGate = field(default_factory = QualityGate)
    curator: Curator = field(default_factory = Curator)
    refineAfterApply: bool = True

    @classmethod
    def fromEnv(cls, memory: ACEMemory) -> "ACEPipeline":
        """Build a pipeline picking the Reflector based on CUTIEE_REFLECTOR."""
        return cls(memory = memory, reflector = buildReflector())

    def processExecution(self, state: AgentState) -> PipelineResult:
        candidates = self.reflector.reflect(state)
        accepted, diagnostics = self.qualityGate.apply(candidates, state)
        if not accepted:
            return PipelineResult(accepted = False, diagnostics = diagnostics)

        existing = list(self.memory.bullets.values())
        delta = self.curator.curate(accepted, existing)
        self.memory.applyDelta(delta)

        removals = 0
        if self.refineAfterApply:
            removals = self.memory.refine()

        return PipelineResult(
            accepted = True,
            diagnostics = diagnostics,
            delta = delta,
            refinedRemovals = removals,
        )

    def retrieveRelevantBullets(self, query: str, k: int = 6) -> list[Bullet]:
        return self.memory.retrieveRelevantBullets(query, k = k)

    def asPromptBlock(self, bullets: list[Bullet]) -> str:
        return self.memory.asPromptBlock(bullets)
