"""Local Qwen selection tests.

These stay unit-level by monkeypatching the model bridge instead of
loading transformers or touching the network.
"""
from __future__ import annotations

import pytest

from agent.harness.state import Action, ActionType, AgentState, ObservationStep
from agent.memory.decomposer import LlmActionDecomposer
from agent.memory.reflector import HeuristicReflector, LlmReflector


def test_local_llm_only_applies_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.memory import local_llm

    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.delenv("CUTIEE_FORCE_LOCAL_LLM", raising = False)
    monkeypatch.setenv("CUTIEE_ENABLE_LOCAL_LLM", "true")

    assert local_llm.shouldUseLocalLlmForUrl("http://localhost:5000/demo") is True
    assert local_llm.shouldUseLocalLlmForUrl("http://127.0.0.1:8000/") is True
    assert local_llm.shouldUseLocalLlmForUrl("https://example.com") is False


def test_decomposer_prefers_local_qwen_for_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("CUTIEE_ENABLE_LOCAL_LLM", "true")
    monkeypatch.delenv("GEMINI_API_KEY", raising = False)

    from agent.memory import local_llm

    monkeypatch.setattr(local_llm, "generateText", lambda **_: """
    {
      "steps": [
        {
          "action_type": "navigate",
          "target": "http://localhost:5000",
          "value": "",
          "description": "open the app"
        },
        {
          "action_type": "finish",
          "target": "",
          "value": "",
          "description": "done"
        }
      ]
    }
    """)

    graph = LlmActionDecomposer().decompose(
        userId = "u",
        taskDescription = "open the demo app",
        initialUrl = "http://localhost:5000",
    )

    assert [node.action_type for node in graph.nodes] == ["navigate", "finish"]


def test_reflector_prefers_local_qwen_for_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("CUTIEE_ENABLE_LOCAL_LLM", "true")
    monkeypatch.delenv("GEMINI_API_KEY", raising = False)

    from agent.memory import local_llm

    monkeypatch.setattr(local_llm, "generateText", lambda **_: """
    {
      "lessons": [
        {
          "content": "Use the localhost form flow in order: open page, fill fields, then submit.",
          "type": "procedural",
          "tags": ["localhost", "form"],
          "confidence": 0.91
        }
      ]
    }
    """)

    state = AgentState(taskId = "t", userId = "u", taskDescription = "submit the localhost form")
    state.history = [
        ObservationStep(
            index = 0,
            url = "http://localhost:5000",
            action = Action(type = ActionType.NAVIGATE, target = "http://localhost:5000"),
        ),
    ]
    state.markComplete("ok")

    lessons = LlmReflector(fallback = HeuristicReflector()).reflect(state)

    assert len(lessons) == 1
    assert lessons[0].memoryType == "procedural"
    assert "localhost" in lessons[0].tags
