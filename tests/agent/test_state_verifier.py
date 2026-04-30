"""Tests for the Phase 4 state verifier.

Verifies the URL-compatibility check, perceptual-hash distance math,
and the verify() entry point's safe/unsafe decision logic.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from agent.memory.state_verifier import (
    DEFAULT_PHASH_HAMMING_THRESHOLD,
    StateVerifier,
    _urlsCompatible,
    computeAverageHash,
    hammingDistance,
)


@dataclass
class _StubNode:
    """Minimal ActionNode-like for testing without circular imports."""

    expected_url: str = ""
    expected_phash: str = ""


def _solidPng(width: int = 16, height: int = 16, value: int = 128) -> bytes:
    """Generate a solid-color PNG so phash is deterministic."""
    from PIL import Image

    img = Image.new("L", (width, height), value)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _gradientPng() -> bytes:
    """A 16x16 PNG with a left-to-right gradient — different phash from solid."""
    from PIL import Image

    img = Image.new("L", (16, 16), 0)
    px = img.load()
    for x in range(16):
        for y in range(16):
            px[x, y] = x * 16
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# === URL compatibility ===


def test_urls_compatible_same_host_same_first_segment() -> None:
    assert _urlsCompatible(
        "https://docs.google.com/spreadsheets/d/abc", "https://docs.google.com/spreadsheets/d/xyz"
    )


def test_urls_compatible_different_hosts_rejected() -> None:
    assert not _urlsCompatible("https://docs.google.com/x", "https://github.com/y")


def test_urls_compatible_different_first_segments_rejected() -> None:
    assert not _urlsCompatible(
        "https://docs.google.com/spreadsheets/d/abc", "https://docs.google.com/document/d/abc"
    )


def test_urls_compatible_empty_inputs_pass() -> None:
    """Missing expected URL means 'don't block on this signal'."""
    assert _urlsCompatible("", "https://x.com/y")
    assert _urlsCompatible("https://x.com/y", "")


# === Perceptual hash ===


def test_phash_identical_images_hash_equal() -> None:
    a = _solidPng(value=200)
    b = _solidPng(value=200)
    assert computeAverageHash(a) == computeAverageHash(b)


def test_phash_different_images_hash_differ() -> None:
    a = _solidPng(value=50)
    b = _gradientPng()
    assert computeAverageHash(a) != computeAverageHash(b)


def test_phash_empty_input_returns_empty() -> None:
    assert computeAverageHash(b"") == ""


def test_hamming_distance_zero_for_identical() -> None:
    h = computeAverageHash(_solidPng(value=150))
    assert hammingDistance(h, h) == 0


def test_hamming_distance_high_for_different() -> None:
    h1 = computeAverageHash(_solidPng(value=30))
    h2 = computeAverageHash(_gradientPng())
    assert hammingDistance(h1, h2) > 0


# === StateVerifier.verify() ===


def test_verify_safe_when_url_and_phash_match() -> None:
    png = _solidPng(value=180)
    node = _StubNode(
        expected_url="https://docs.google.com/spreadsheets/d/abc",
        expected_phash=computeAverageHash(png),
    )
    v = StateVerifier()
    result = v.verify(
        node=node,
        currentUrl="https://docs.google.com/spreadsheets/d/xyz",  # same host+seg
        currentScreenshot=png,
    )
    assert result.safe is True
    assert result.urlMatch is True
    assert result.phashDistance == 0


def test_verify_unsafe_when_url_mismatches() -> None:
    png = _solidPng(value=180)
    node = _StubNode(
        expected_url="https://docs.google.com/spreadsheets/d/abc",
        expected_phash=computeAverageHash(png),
    )
    v = StateVerifier()
    result = v.verify(
        node=node,
        currentUrl="https://github.com/foo/bar",
        currentScreenshot=png,
    )
    assert result.safe is False
    assert result.urlMatch is False


def test_verify_unsafe_when_phash_diverges() -> None:
    expectedPng = _solidPng(value=50)
    actualPng = _gradientPng()
    node = _StubNode(
        expected_url="https://x.com/page",
        expected_phash=computeAverageHash(expectedPng),
    )
    v = StateVerifier(phashThreshold=5)  # tight threshold for the test
    result = v.verify(
        node=node,
        currentUrl="https://x.com/page",
        currentScreenshot=actualPng,
    )
    assert result.safe is False
    assert result.urlMatch is True
    assert result.phashDistance is not None
    assert result.phashDistance > 5


def test_verify_skips_phash_when_expected_field_empty() -> None:
    """Backwards-compat: ActionNodes saved before Phase 4 lack expected_phash."""
    node = _StubNode(expected_url="https://x.com/page", expected_phash="")
    v = StateVerifier()
    result = v.verify(
        node=node,
        currentUrl="https://x.com/page",
        currentScreenshot=_solidPng(),
    )
    assert result.safe is True
    assert result.phashDistance is None


def test_verify_default_threshold_value() -> None:
    """Sanity: ensure the default isn't accidentally changed."""
    assert DEFAULT_PHASH_HAMMING_THRESHOLD == 16
    v = StateVerifier()
    assert v.phashThreshold == 16
