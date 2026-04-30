from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.harness.state import Action, ActionType
from agent.routing.models.gemini_cu import MockComputerUseClient
from apps.tasks import runner_factory


@dataclass
class _Preference:
    redact_audit_screenshots: bool = False


def test_liveRunnerWiresConfigGuardrailsAndSingleMemoryWrite(monkeypatch) -> None:
    capturedConfig: dict[str, Any] = {}

    class _UserManager:
        def filter(self, **_kwargs):
            return self

        def first(self):
            return None

    class _User:
        objects = _UserManager()

    def fakeBuildClient(**kwargs):
        capturedConfig["config"] = kwargs["config"]
        return MockComputerUseClient(
            actionsToReturn = [Action(type = ActionType.FINISH, reasoning = "done")],
            fixedCostUsd = 0.001,
        )

    monkeypatch.setenv("CUTIEE_MAX_COST_USD_PER_TASK", "0.02")
    monkeypatch.setenv("CUTIEE_MAX_COST_USD_PER_HOUR", "0.10")
    monkeypatch.setenv("CUTIEE_MAX_COST_USD_PER_DAY", "0.20")
    monkeypatch.setenv("CUTIEE_HEARTBEAT_MINUTES", "3")
    monkeypatch.setenv("CUTIEE_REPLAY_FRAGMENT_CONFIDENCE", "0.91")
    monkeypatch.setattr(runner_factory.ACEMemory, "loadFromStore", lambda _self: None)
    monkeypatch.setattr(runner_factory, "_buildCuClientFromEnv", fakeBuildClient)
    monkeypatch.setattr("django.contrib.auth.get_user_model", lambda: _User)

    from apps.accounts.models import UserPreference

    monkeypatch.setattr(UserPreference, "for_user", staticmethod(lambda _user: _Preference()))

    runner = runner_factory.buildLiveCuRunnerForUser(
        userId = "user-1",
        initialUrl = "https://example.com/start",
        useStubBrowser = True,
    )

    assert runner.memory is None
    assert runner.maxCostUsdPerTask == 0.02
    assert runner.maxCostUsdPerHour == 0.10
    assert runner.maxCostUsdPerDay == 0.20
    assert runner.heartbeat is not None
    assert runner.injectionGuard is not None
    assert runner.captchaDetector is not None
    assert runner.fragmentMatcher is not None
    assert capturedConfig["config"].replayFragmentConfidence == 0.91
