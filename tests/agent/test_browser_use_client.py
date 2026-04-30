"""Phase 1 tests for the browser-use CU client adapter.

Covers three things the plan mandates:
1. The adapter satisfies the `CuClient` Protocol.
2. It validates `GEMINI_API_KEY` at construction time.
3. Actions emitted by the adapter round-trip through the replay
   reconstruction at `agent/memory/replay.py:_actionFromBullet`. This is
   the hard contract that prevents a new adapter from silently breaking
   replay by emitting non-canonical action names.
"""

from __future__ import annotations

import pytest

from agent.harness.state import ActionType
from agent.memory.bullet import Bullet
from agent.memory.replay import _actionFromBullet
from agent.routing.cu_client import CuClient
from agent.routing.models.browser_use_client import (
    BROWSER_USE_PRICING,
    DEFAULT_BROWSER_USE_MODEL,
    BrowserUseClient,
    _toCanonicalAction,
)


@pytest.fixture
def _browserUseInstalled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake browser-use presence by inserting a stub module into sys.modules."""
    import sys
    import types

    if "browser_use" in sys.modules:
        return

    stub = types.ModuleType("browser_use")
    stub.Agent = object  # type: ignore[attr-defined]
    stub.Browser = object  # type: ignore[attr-defined]
    llm_stub = types.ModuleType("browser_use.llm")
    llm_stub.ChatGoogle = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "browser_use", stub)
    monkeypatch.setitem(sys.modules, "browser_use.llm", llm_stub)


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        BrowserUseClient()


def test_missing_package_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    with pytest.raises(RuntimeError, match="browser-use is not installed"):
        BrowserUseClient()


def test_client_satisfies_protocol(
    monkeypatch: pytest.MonkeyPatch,
    _browserUseInstalled: None,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    client = BrowserUseClient()
    assert isinstance(client, CuClient)
    assert client.modelId == DEFAULT_BROWSER_USE_MODEL
    assert DEFAULT_BROWSER_USE_MODEL in BROWSER_USE_PRICING


def test_click_by_index_maps_to_click_at() -> None:
    rawStep = {
        "action_name": "click_element_by_index",
        "args": {
            "index": 7,
            "bbox": {"x": 100, "y": 50, "width": 80, "height": 40},
        },
    }
    action, rawName, rawArgs, meta = _toCanonicalAction(rawStep, "https://ex.com")
    assert action.type == ActionType.CLICK_AT
    assert action.coordinate == (140, 70)
    assert rawName == "click_element_by_index"
    assert meta.get("element_index") == 7


def test_input_text_maps_to_type_at() -> None:
    rawStep = {
        "action_name": "input_text",
        "args": {
            "index": 3,
            "bbox": [100, 200, 300, 240],
            "text": "hello world",
        },
    }
    action, _, _, _ = _toCanonicalAction(rawStep, "https://ex.com")
    assert action.type == ActionType.TYPE_AT
    assert action.coordinate == (200, 220)
    assert action.value == "hello world"


def test_scroll_down_maps_to_scroll_at() -> None:
    rawStep = {"action_name": "scroll_down", "args": {"amount": 500}}
    action, _, _, _ = _toCanonicalAction(rawStep, "https://ex.com")
    assert action.type == ActionType.SCROLL_AT
    assert action.scrollDy == 500


def test_scroll_up_maps_to_negative_scroll() -> None:
    rawStep = {"action_name": "scroll_up", "args": {"amount": 400}}
    action, _, _, _ = _toCanonicalAction(rawStep, "https://ex.com")
    assert action.type == ActionType.SCROLL_AT
    assert action.scrollDy == -400


def test_go_to_url_maps_to_navigate() -> None:
    rawStep = {"action_name": "go_to_url", "args": {"url": "https://example.com/foo"}}
    action, _, _, _ = _toCanonicalAction(rawStep, "https://prev.com")
    assert action.type == ActionType.NAVIGATE
    assert action.target == "https://example.com/foo"


def test_done_maps_to_finish() -> None:
    rawStep = {"action_name": "done", "args": {}}
    action, _, _, _ = _toCanonicalAction(rawStep, "https://ex.com")
    assert action.type == ActionType.FINISH


def test_send_keys_maps_to_key_combo() -> None:
    rawStep = {"action_name": "send_keys", "args": {"keys": "Control+A"}}
    action, _, _, _ = _toCanonicalAction(rawStep, "https://ex.com")
    assert action.type == ActionType.KEY_COMBO
    assert action.keys == ["Control", "A"]


@pytest.mark.parametrize(
    "rawName",
    [
        "click_element_by_index",
        "input_text",
        "scroll_down",
        "scroll_up",
        "go_to_url",
        "send_keys",
        "done",
    ],
)
def test_action_round_trips_through_replay(rawName: str) -> None:
    """Hard contract: every adapter emits canonical ActionType values.

    Replay reconstructs actions by regex-parsing `action=<name>` out of
    bullet content. If the adapter emits a non-canonical name, the
    reconstructed bullet silently drops from the replay plan.
    """
    rawStep = {
        "action_name": rawName,
        "args": {
            "index": 1,
            "bbox": {"x": 0, "y": 0, "width": 10, "height": 10},
            "text": "v",
            "amount": 100,
            "url": "https://ex.com/next",
            "keys": "Enter",
        },
    }
    action, _, _, _ = _toCanonicalAction(rawStep, "https://ex.com")
    assert action.type in ActionType

    bulletContent = (
        f"step_index=0 action={action.type.value} "
        f"target={action.target!r} value={(action.value or '')!r}"
    )
    if action.coordinate is not None:
        bulletContent += f" coordinate=({action.coordinate[0]},{action.coordinate[1]})"
    if action.scrollDx or action.scrollDy:
        bulletContent += f" scroll=({action.scrollDx},{action.scrollDy})"
    if action.keys:
        bulletContent += f" keys={','.join(action.keys)}"

    bullet = Bullet(
        id="test-round-trip",
        content=bulletContent,
        memory_type="procedural",
    )
    parsed = _actionFromBullet(bullet)
    assert parsed is not None
    assert parsed.type == action.type
