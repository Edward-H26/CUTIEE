"""Regression tests for the CU model selection.

The default `gemini-flash-latest` was chosen because it
(a) supports the ComputerUse tool natively (verified live 2026-04-19),
(b) tracks Google's latest Flash so we get auto-upgrade,
(c) costs ~8x less than the dedicated 2.5 CU specialty preview.

These tests guard against accidental regressions: someone re-pointing
the default at a model that doesn't support CU (gemini-3.1-flash-lite-preview)
or a model that's pro-priced (the 2.5 specialty preview) would silently
break runs or burn budget.
"""
from __future__ import annotations

import os

import pytest

from agent.routing.models import gemini_cu


def test_default_model_is_supported() -> None:
    assert gemini_cu.DEFAULT_MODEL in gemini_cu.SUPPORTED_CU_MODELS


def test_default_model_is_flash_priced() -> None:
    """Default must be flash-priced ($0.15 in / $0.60 out per MT)."""
    priceIn, priceOut = gemini_cu.CU_PRICING[gemini_cu.DEFAULT_MODEL]
    assert priceIn == 0.15, f"default in-price should be flash ($0.15), got {priceIn}"
    assert priceOut == 0.60, f"default out-price should be flash ($0.60), got {priceOut}"


def test_supported_set_excludes_known_unsupported_models() -> None:
    """The live API rejects these with 400 'Computer Use is not enabled'."""
    for unsupported in ("gemini-3.1-flash-lite-preview", "gemini-3.1-flash"):
        assert unsupported not in gemini_cu.SUPPORTED_CU_MODELS, (
            f"{unsupported!r} does not support CU and should not be in SUPPORTED_CU_MODELS"
        )


def test_specialty_preview_kept_for_opt_in() -> None:
    """The 2.5 CU specialty preview stays available for users who opt in."""
    assert "gemini-2.5-computer-use-preview-10-2025" in gemini_cu.SUPPORTED_CU_MODELS


def test_env_override_changes_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """CUTIEE_CU_MODEL env var should override the default at import time.

    Re-imports the module to pick up the new env var. This guards the
    deployment story: production sets CUTIEE_CU_MODEL=<pinned-id> for
    deterministic replay across Google model swaps.
    """
    monkeypatch.setenv("CUTIEE_CU_MODEL", "gemini-3-flash-preview")
    import importlib

    reloaded = importlib.reload(gemini_cu)
    try:
        assert reloaded.DEFAULT_MODEL == "gemini-3-flash-preview"
    finally:
        # Restore the original module state so subsequent tests get the
        # real default.
        monkeypatch.delenv("CUTIEE_CU_MODEL", raising = False)
        importlib.reload(gemini_cu)


def test_construction_with_default_model() -> None:
    """The client constructor must accept the default without raising.

    Uses a stub key — this test does not hit the live API.
    """
    os.environ.setdefault("GEMINI_API_KEY", "stub-for-test")
    client = gemini_cu.GeminiComputerUseClient()
    assert client.modelId == gemini_cu.DEFAULT_MODEL
