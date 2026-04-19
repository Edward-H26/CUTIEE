"""Self-evolving pipeline orchestrating Reflector → QualityGate → Curator.

The pipeline is the single entry point the orchestrator calls after every
finished task. It owns the policy decisions (which reflector to use, which
gate threshold, whether to refine after applying the delta) so callers don't
have to know the internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.harness.state import AgentState
from agent.memory.ace_memory import ACEMemory
from agent.memory.curator import Curator
from agent.memory.quality_gate import QualityGate, QualityGateDiagnostics
from agent.memory.reflector import HeuristicReflector
from apps.memory_app.bullet import Bullet, DeltaUpdate


@dataclass
class PipelineResult:
    accepted: bool
    diagnostics: QualityGateDiagnostics
    delta: DeltaUpdate = field(default_factory = DeltaUpdate)
    refinedRemovals: int = 0


@dataclass
class ACEPipeline:
    memory: ACEMemory
    reflector: HeuristicReflector = field(default_factory = HeuristicReflector)
    qualityGate: QualityGate = field(default_factory = QualityGate)
    curator: Curator = field(default_factory = Curator)
    refineAfterApply: bool = True

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
