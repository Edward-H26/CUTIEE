"""Unit tests for the ACE memory pipeline pieces that don't touch Neo4j."""

from __future__ import annotations

from agent.harness.state import Action, ActionType, AgentState, ObservationStep
from agent.memory.curator import Curator
from agent.memory.decay import (
    EPISODIC_DECAY_RATE,
    PROCEDURAL_DECAY_RATE,
    SEMANTIC_DECAY_RATE,
    decayedStrength,
    totalDecayedStrength,
)
from agent.memory.embeddings import cosineSimilarity, hashEmbedding
from agent.memory.quality_gate import QualityGate
from agent.memory.reflector import HeuristicReflector, LessonCandidate
from apps.memory_app.bullet import Bullet, DeltaUpdate


def test_decayConstantsOrderedCorrectly():
    assert PROCEDURAL_DECAY_RATE < SEMANTIC_DECAY_RATE < EPISODIC_DECAY_RATE


def test_decayedStrengthZeroDelta():
    assert decayedStrength(1.0, 0, SEMANTIC_DECAY_RATE) == 1.0


def test_episodicFadesFasterThanProcedural():
    bullet = Bullet(
        content="x", memory_type="procedural", episodic_strength=1.0, procedural_strength=1.0
    )
    bullet.episodic_access_index = 0
    bullet.procedural_access_index = 0
    bullet.semantic_access_index = 0
    after100 = totalDecayedStrength(bullet, currentClock=100)
    after1000 = totalDecayedStrength(bullet, currentClock=1000)
    assert after100 > after1000


def test_bulletDefaultsByType():
    procedural = Bullet(content="x", memory_type="procedural")
    assert procedural.procedural_strength == 1.0
    semantic = Bullet(content="x", memory_type="semantic")
    assert semantic.semantic_strength == 1.0


def test_deltaUpdateIsEmptyDetection():
    assert DeltaUpdate().isEmpty() is True
    assert DeltaUpdate(new_bullets=[Bullet(content="x", memory_type="semantic")]).isEmpty() is False


def test_hashEmbeddingDeterministicAndCosine1ForIdenticalText():
    a = hashEmbedding("hello world")
    b = hashEmbedding("hello world")
    assert a == b
    assert cosineSimilarity(a, b) == 1.0


def test_cosineHandlesEmpty():
    assert cosineSimilarity([], [1, 2]) == 0.0
    assert cosineSimilarity(None, [1]) == 0.0


def test_reflectorEmitsProceduralLessonsForSuccessfulSteps():
    state = AgentState(taskId="t", userId="u", taskDescription="open the page and click submit")
    state.history = [
        ObservationStep(
            index=0,
            url="http://example.com",
            action=Action(type=ActionType.NAVIGATE, target="http://example.com", confidence=0.9),
        ),
        ObservationStep(
            index=1,
            url="http://example.com",
            action=Action(type=ActionType.CLICK, target="#submit", confidence=0.85),
        ),
    ]
    state.markComplete("ok")
    candidates = HeuristicReflector().reflect(state)
    assert any(c.memoryType == "procedural" for c in candidates)
    assert any(c.memoryType == "episodic" for c in candidates)


def test_qualityGateAcceptsHighConfidence():
    candidates = [
        LessonCandidate(
            content="step 1: navigate to url", memoryType="procedural", confidence=0.85, tags=["a"]
        ),
        LessonCandidate(
            content="step 2: click submit", memoryType="procedural", confidence=0.85, tags=["a"]
        ),
    ]
    state = AgentState(taskId="t", userId="u", taskDescription="x")
    state.history = [ObservationStep(index=0, action=Action(type=ActionType.CLICK))]
    state.markComplete("ok")
    accepted, diag = QualityGate().apply(candidates, state)
    assert accepted == candidates
    assert diag.accepted is True


def test_qualityGateRejectsLowConfidence():
    candidates = [LessonCandidate(content="x", memoryType="semantic", confidence=0.3)]
    state = AgentState(taskId="t", userId="u", taskDescription="x")
    state.markComplete("ok")
    accepted, diag = QualityGate().apply(candidates, state)
    assert accepted == []
    assert diag.accepted is False
    assert "top_confidence_low" in diag.reasons


def test_curatorEmitsNewBulletsForNovelLessons():
    lesson = LessonCandidate(
        content="new lesson about a workflow step", memoryType="procedural", confidence=0.9
    )
    delta = Curator().curate([lesson], existing=[])
    assert len(delta.new_bullets) == 1
    assert delta.new_bullets[0].memory_type == "procedural"
