"""Phase 0 conformance tests for the CuClient Protocol.

`ComputerUseRunner.client` is typed as `CuClient`, not `Any`. Anything a
runner accepts as a client must satisfy `isinstance(client, CuClient)`
at import time, not at the first screenshot call. This test pins the
two existing clients (Gemini and Mock) to the Protocol so a future
adapter that drops one of the required methods fails here instead of
inside the runner's loop.
"""

from __future__ import annotations

import pytest

from agent.routing.cu_client import CuClient, ComputerUseStep
from agent.routing.models.gemini_cu import (
    GeminiComputerUseClient,
    MockComputerUseClient,
)


def test_mock_client_satisfies_protocol() -> None:
    client = MockComputerUseClient(
        label="mock-cu-test",
        actionsToReturn=[],
        fixedCostUsd=0.0,
    )
    assert isinstance(client, CuClient)


def test_gemini_client_satisfies_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-for-protocol-check")
    client = GeminiComputerUseClient()
    assert isinstance(client, CuClient)


def test_computer_use_step_shape() -> None:
    from agent.harness.state import Action, ActionType

    step = ComputerUseStep(
        action=Action(type=ActionType.FINISH, reasoning="protocol-check"),
        rawFunctionName="finished",
        rawArgs={},
        costUsd=0.0,
    )
    assert step.action.type == ActionType.FINISH
    assert step.rawFunctionName == "finished"
    assert step.costUsd == 0.0
