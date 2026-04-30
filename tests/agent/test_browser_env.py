"""Smoke tests for env_utils + browserFromEnv.

These guard the failure mode where a `.env` typo silently flips the
default behavior (e.g., `CUTIEE_BROWSER_HEADLESS=tru` should NOT enable
headless mode just because something was set).
"""

from __future__ import annotations

import pytest

from agent.browser.controller import BrowserController, browserFromEnv
from agent.harness.env_utils import envBool, envFloat, envInt, envStr


@pytest.fixture(autouse=True)
def _clearEnv(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "CUTIEE_BROWSER_HEADLESS",
        "CUTIEE_BROWSER_SLOW_MO_MS",
        "CUTIEE_STORAGE_STATE_PATH",
        "CUTIEE_BROWSER_CDP_URL",
        "CUTIEE_TEST_FOO",
    ):
        monkeypatch.delenv(key, raising=False)


def test_envBool_default_when_unset() -> None:
    assert envBool("CUTIEE_TEST_FOO", True) is True
    assert envBool("CUTIEE_TEST_FOO", False) is False


def test_envBool_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "TRUE", "yes", "Y", "on"):
        monkeypatch.setenv("CUTIEE_TEST_FOO", value)
        assert envBool("CUTIEE_TEST_FOO", False) is True, f"{value!r} should be truthy"


def test_envBool_falsy(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("CUTIEE_TEST_FOO", value)
        # empty string falls back to default; everything else is explicitly false.
        result = envBool("CUTIEE_TEST_FOO", True)
        if value == "":
            assert result is True
        else:
            assert result is False, f"{value!r} should be falsy"


def test_envBool_garbage_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """The original bug: 'tru' would be treated as truthy via `value.startswith`.
    The new helper requires exact match against the truthy set."""
    monkeypatch.setenv("CUTIEE_TEST_FOO", "tru")
    assert envBool("CUTIEE_TEST_FOO", False) is False


def test_envInt_default_on_missing_or_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    assert envInt("CUTIEE_TEST_FOO", 7) == 7
    monkeypatch.setenv("CUTIEE_TEST_FOO", "not-a-number")
    assert envInt("CUTIEE_TEST_FOO", 7) == 7
    monkeypatch.setenv("CUTIEE_TEST_FOO", "42")
    assert envInt("CUTIEE_TEST_FOO", 7) == 42


def test_envFloat_default_on_missing_or_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    assert envFloat("CUTIEE_TEST_FOO", 0.5) == 0.5
    monkeypatch.setenv("CUTIEE_TEST_FOO", "garbage")
    assert envFloat("CUTIEE_TEST_FOO", 0.5) == 0.5
    monkeypatch.setenv("CUTIEE_TEST_FOO", "1.25")
    assert envFloat("CUTIEE_TEST_FOO", 0.5) == 1.25


def test_envStr_returns_default_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_TEST_FOO", "")
    assert envStr("CUTIEE_TEST_FOO", "fallback") == "fallback"
    monkeypatch.setenv("CUTIEE_TEST_FOO", "value")
    assert envStr("CUTIEE_TEST_FOO", "fallback") == "value"


def test_browserFromEnv_default_visible() -> None:
    ctrl = browserFromEnv(defaultHeadless=False)
    assert isinstance(ctrl, BrowserController)
    assert ctrl.headless is False
    assert ctrl.cdpUrl is None
    assert ctrl.slowMoMs == 0


def test_browserFromEnv_headless_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_BROWSER_HEADLESS", "1")
    ctrl = browserFromEnv(defaultHeadless=False)
    assert ctrl.headless is True


def test_browserFromEnv_slowmo_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_BROWSER_SLOW_MO_MS", "250")
    ctrl = browserFromEnv()
    assert ctrl.slowMoMs == 250


def test_browserFromEnv_cdp_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_BROWSER_CDP_URL", "http://localhost:9222")
    ctrl = browserFromEnv()
    assert ctrl.cdpUrl == "http://localhost:9222"


def test_browserFromEnv_storage_state_only_if_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Setting the env var to a non-existent file should NOT crash;
    Playwright would error on launch, so we silently drop missing paths."""
    monkeypatch.setenv("CUTIEE_STORAGE_STATE_PATH", str(tmp_path / "nope.json"))
    ctrl = browserFromEnv()
    assert ctrl.storageStatePath is None

    real = tmp_path / "real.json"
    real.write_text("{}")
    monkeypatch.setenv("CUTIEE_STORAGE_STATE_PATH", str(real))
    ctrl2 = browserFromEnv()
    assert ctrl2.storageStatePath == str(real)


def test_browserFromEnv_per_domain_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    chdir_tmp,
) -> None:
    """If data/storage_state/<domain>.json exists, prefer it over the global path."""
    domainDir = tmp_path / "data" / "storage_state"
    domainDir.mkdir(parents=True)
    googlePath = domainDir / "docs.google.com.json"
    googlePath.write_text("{}")

    globalPath = tmp_path / "global.json"
    globalPath.write_text("{}")
    monkeypatch.setenv("CUTIEE_STORAGE_STATE_PATH", str(globalPath))

    ctrl = browserFromEnv(domain="docs.google.com")
    assert ctrl.storageStatePath == str(
        googlePath.relative_to(tmp_path)
    ) or ctrl.storageStatePath == str(googlePath)


@pytest.fixture
def chdir_tmp(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path
