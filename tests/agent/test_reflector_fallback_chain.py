"""Chaos tests for the three-tier reflector fallback chain.

The reflector at `agent/memory/reflector.py:303-318` chains three implementations:
local Qwen 3.5-0.8B for localhost URLs, Gemini Flash for everything else, and a
deterministic heuristic floor as the last resort. The tests below force each
upstream tier to raise inside a single `reflect()` call and assert that the
heuristic floor still emits lessons rather than letting the memory writeback
fail silently. They complement `tests/agent/test_local_llm.py` which only
covers the happy path where Qwen succeeds.

These stay unit-level by monkeypatching `local_llm.generateText` and
`LlmReflector._reflectViaGemini` so the test never touches the network or
loads transformers weights.
"""

from __future__ import annotations

import pytest

from agent.harness.state import Action, ActionType, AgentState, ObservationStep
from agent.memory.reflector import HeuristicReflector, LessonCandidate, LlmReflector


def _buildLocalhostState() -> AgentState:
    state = AgentState(taskId="t", userId="u", taskDescription="submit the localhost form")
    state.history = [
        ObservationStep(
            index=0,
            url="http://localhost:5000",
            action=Action(type=ActionType.NAVIGATE, target="http://localhost:5000"),
            verificationOk=True,
        ),
    ]
    state.markComplete("ok")
    return state


def _installSentinelClient(reflector: LlmReflector) -> None:
    """Force `reflect()` to take the Gemini-call branch.

    `LlmReflector.__post_init__` sets `self._client = None` whenever the
    `google.genai` package is missing or `GEMINI_API_KEY` is unset. The
    `reflect()` method then short-circuits to the fallback before
    `_reflectViaGemini` ever runs. The chaos test needs to verify what
    happens *when Gemini itself raises*, so we install a truthy sentinel
    client after construction. The monkeypatched `_reflectViaGemini` will
    never actually call `_client.models.generate_content`, so the sentinel
    does not need to be a working `google.genai.Client`.
    """
    reflector._client = object()


def test_reflector_falls_back_to_heuristic_when_qwen_and_gemini_both_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end chaos test for `agent/memory/reflector.py:303-318`.

    Both upstream tiers raise within the same `reflect()` call:
    1. Qwen path: `local_llm.generateText` raises a RuntimeError.
    2. Gemini path: `_reflectViaGemini` raises a RuntimeError.

    The HeuristicReflector floor must still emit at least one lesson so the
    ACE pipeline does not lose memory writeback for a successful task.
    """
    from agent.memory import local_llm

    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("CUTIEE_ENABLE_LOCAL_LLM", "true")
    monkeypatch.setenv("ACE_REFLECTION_ENABLED", "true")

    def raiseQwenFailure(**_: object) -> str:
        raise RuntimeError("simulated Qwen runtime failure")

    def raiseGeminiFailure(self: LlmReflector, state: AgentState) -> list[LessonCandidate]:
        del self, state
        raise RuntimeError("simulated Gemini runtime failure")

    monkeypatch.setattr(local_llm, "generateText", raiseQwenFailure)
    monkeypatch.setattr(LlmReflector, "_reflectViaGemini", raiseGeminiFailure)

    state = _buildLocalhostState()
    reflector = LlmReflector(fallback=HeuristicReflector(minConfidence=0.5))
    _installSentinelClient(reflector)

    lessons = reflector.reflect(state)

    assert len(lessons) >= 1, (
        "HeuristicReflector floor should emit at least one lesson when both "
        "Qwen and Gemini paths raise"
    )
    memoryTypes = {lesson.memoryType for lesson in lessons}
    assert memoryTypes.issubset({"procedural", "episodic", "semantic"}), (
        f"All emitted lessons should belong to one of the three ACE channels; " f"got {memoryTypes}"
    )


def test_reflector_skips_qwen_for_non_localhost_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the URL is not localhost the local-Qwen path is never invoked.

    This is the "wrong-URL guard" companion to the chaos test: it confirms
    that `shouldUseLocalLlmForUrl` correctly skips Qwen for production URLs,
    so a malfunctioning Qwen install cannot poison reflection on real
    workloads. Gemini raises, and the heuristic floor still wins.
    """
    from agent.memory import local_llm

    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("ACE_REFLECTION_ENABLED", "true")

    qwenInvocations: list[object] = []

    def trackQwen(**kwargs: object) -> str:
        qwenInvocations.append(kwargs)
        raise RuntimeError("Qwen should not have been invoked for non-localhost URLs")

    def raiseGeminiFailure(self: LlmReflector, state: AgentState) -> list[LessonCandidate]:
        del self, state
        raise RuntimeError("simulated Gemini runtime failure")

    monkeypatch.setattr(local_llm, "generateText", trackQwen)
    monkeypatch.setattr(LlmReflector, "_reflectViaGemini", raiseGeminiFailure)

    state = AgentState(
        taskId="t",
        userId="u",
        taskDescription="open the demo and click submit",
    )
    state.history = [
        ObservationStep(
            index=0,
            url="https://example.com/demo",
            action=Action(type=ActionType.NAVIGATE, target="https://example.com/demo"),
            verificationOk=True,
        ),
    ]
    state.markComplete("ok")

    reflector = LlmReflector(fallback=HeuristicReflector(minConfidence=0.5))
    _installSentinelClient(reflector)

    lessons = reflector.reflect(state)

    assert len(lessons) >= 1, "Heuristic floor should still emit lessons on non-localhost URL"
    assert (
        qwenInvocations == []
    ), "Qwen path must not be invoked for non-localhost URLs even when Gemini raises"


def test_reflector_uses_qwen_then_falls_through_when_qwen_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mid-failure path: Qwen returns an empty list; Gemini path is used.

    `LlmReflector.reflect` only returns Qwen's output when `lessons` is
    truthy. An empty list (e.g., Qwen JSON parsed but contained zero
    lessons) must fall through to Gemini rather than letting the memory
    writeback finish empty.
    """
    from agent.memory import local_llm

    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("CUTIEE_ENABLE_LOCAL_LLM", "true")
    monkeypatch.setenv("ACE_REFLECTION_ENABLED", "true")

    monkeypatch.setattr(
        local_llm,
        "generateText",
        lambda **_: '{"lessons": []}',
    )

    geminiInvocations: list[AgentState] = []

    def captureGemini(self: LlmReflector, state: AgentState) -> list[LessonCandidate]:
        del self
        geminiInvocations.append(state)
        return [
            LessonCandidate(
                content="Gemini path emitted this lesson after Qwen returned empty",
                memoryType="procedural",
                confidence=0.9,
                tags=["test", "fallback"],
            )
        ]

    monkeypatch.setattr(LlmReflector, "_reflectViaGemini", captureGemini)

    state = _buildLocalhostState()
    reflector = LlmReflector(fallback=HeuristicReflector(minConfidence=0.5))
    _installSentinelClient(reflector)

    lessons = reflector.reflect(state)

    assert (
        len(geminiInvocations) == 1
    ), "Gemini path should be invoked exactly once when Qwen returns an empty lesson list"
    assert len(lessons) == 1
    assert lessons[0].memoryType == "procedural"
