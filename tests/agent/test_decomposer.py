"""LlmActionDecomposer fallback tests.

Covers the empty-graph fallback path that the decomposer takes when both
the local Qwen tier and the Gemini tier are unavailable. Local Qwen is
disabled by clearing the env vars that gate `shouldUseLocalLlmForUrl`,
and the Gemini path is short-circuited by leaving `apiKey` unset so
`__post_init__` sets `_client=None`.
"""

from __future__ import annotations

import pytest

from agent.memory.action_graph import ProcedureGraph
from agent.memory.decomposer import LlmActionDecomposer


def test_decompose_returns_empty_graph_when_local_and_gemini_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "production")
    monkeypatch.setenv("CUTIEE_ENABLE_LOCAL_LLM", "false")
    monkeypatch.delenv("CUTIEE_FORCE_LOCAL_LLM", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    decomposer = LlmActionDecomposer(apiKey=None)
    graph = decomposer.decompose(
        userId="user-1",
        taskDescription="open the demo spreadsheet and read row 1",
        initialUrl="https://docs.google.com/spreadsheets/d/abc",
    )

    assert isinstance(graph, ProcedureGraph)
    assert graph.user_id == "user-1"
    assert graph.task_description == "open the demo spreadsheet and read row 1"
    assert graph.nodes == []
    assert graph.edges == []
    assert graph.procedure_id


def test_decompose_falls_back_to_empty_when_local_call_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("CUTIEE_ENABLE_LOCAL_LLM", "true")
    monkeypatch.setenv("CUTIEE_FORCE_LOCAL_LLM", "true")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from agent.memory import local_llm

    def explode(**_: object) -> str:
        raise RuntimeError("simulated torch OOM")

    monkeypatch.setattr(local_llm, "generateText", explode)

    decomposer = LlmActionDecomposer(apiKey=None)
    graph = decomposer.decompose(
        userId="user-2",
        taskDescription="submit the wizard",
        initialUrl="http://localhost:5003/wizard",
    )

    assert isinstance(graph, ProcedureGraph)
    assert graph.user_id == "user-2"
    assert graph.nodes == []


def test_decompose_falls_back_to_empty_when_local_emits_no_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "local")
    monkeypatch.setenv("CUTIEE_ENABLE_LOCAL_LLM", "true")
    monkeypatch.setenv("CUTIEE_FORCE_LOCAL_LLM", "true")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from agent.memory import local_llm

    monkeypatch.setattr(local_llm, "generateText", lambda **_: '{"steps": []}')

    decomposer = LlmActionDecomposer(apiKey=None)
    graph = decomposer.decompose(
        userId="user-3",
        taskDescription="noop",
        initialUrl="http://localhost:5001/",
    )

    assert isinstance(graph, ProcedureGraph)
    assert graph.nodes == []
