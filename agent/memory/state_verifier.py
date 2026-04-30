"""State verification for safe mid-task replay.

The Phase 4 upgrade over option (a) prefix-only replay. Lets the runner
safely replay a stored ActionNode AT ANY POSITION in a new task, not
just contiguous from step 0, by first verifying the current page state
matches what the stored node expects.

Two signals:

  1. **URL fingerprint** — recorded as `expected_url` on the ActionNode
     at save time (taken from `step.url` after the action completed).
     Verifier checks that current URL has the same host + first path
     segment. Catches the common case where a previous fresh step
     navigated to a different URL than what the stored step expected.

  2. **Screenshot perceptual hash** — recorded as `expected_phash` (an
     8x8 average-hash bitmap) at save time. Verifier compares current
     screenshot's phash to expected; replays only if Hamming distance
     is below `phashThreshold` (default 16, i.e., <25% bit difference).

A node passes verification only when BOTH signals agree (or when the
expected fields are empty, in which case verification is skipped — so
old ActionNodes saved before this Phase 4 upgrade still work).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("cutiee.state_verifier")

DEFAULT_PHASH_HAMMING_THRESHOLD = 16  # max bit-difference (out of 64) to count as "same"


@dataclass
class VerificationResult:
    """Outcome of a single state-verification check."""

    safe: bool
    reason: str  # human-readable diagnosis (for audit log)
    urlMatch: bool
    phashDistance: int | None  # None if either side lacked a phash


def computeAverageHash(pngBytes: bytes, hashSize: int = 8) -> str:
    """Compute an 8x8 perceptual aHash of a PNG.

    Algorithm:
      1. Convert to grayscale
      2. Downsize to hashSize x hashSize (lossy, smooths out noise)
      3. Compute mean pixel value
      4. Bit per pixel: 1 if above mean, 0 otherwise
      5. Pack into a 16-char hex string (64 bits)

    Robust to minor pixel shifts, timestamp watermarks, and color
    variations. Less robust to layout shifts (in which case the hashes
    diverge significantly — which is the right answer; the page IS
    different).
    """
    if not pngBytes:
        return ""
    try:
        from PIL import Image
    except ImportError:
        # Fallback: use sha256 (strict — any byte change defeats it).
        # Marked with a sentinel prefix so verifier knows it's degraded.
        import hashlib

        return "sha256:" + hashlib.sha256(pngBytes).hexdigest()[:16]

    try:
        img = (
            Image.open(io.BytesIO(pngBytes))
            .convert("L")
            .resize(
                (hashSize, hashSize),
                Image.Resampling.LANCZOS,
            )
        )
        pixels = list(img.getdata())
        if not pixels:
            return ""
        avg = sum(pixels) / len(pixels)
        bits = 0
        for i, px in enumerate(pixels):
            if px > avg:
                bits |= 1 << i
        return f"{bits:016x}"
    except Exception as exc:  # noqa: BLE001 - perceptual hash is best-effort
        logger.debug("computeAverageHash failed: %s", exc)
        return ""


def hammingDistance(hashA: str, hashB: str) -> int:
    """Bit-difference between two phash hex strings. Returns -1 on incompatible inputs."""
    if not hashA or not hashB:
        return -1
    # Reject mixed sha256/aHash comparisons (they'll never match meaningfully).
    if hashA.startswith("sha256:") != hashB.startswith("sha256:"):
        return -1
    if hashA.startswith("sha256:"):
        # Strict equality check for the sha256 fallback path
        return 0 if hashA == hashB else 64
    try:
        return bin(int(hashA, 16) ^ int(hashB, 16)).count("1")
    except ValueError:
        return -1


def _urlsCompatible(expectedUrl: str, currentUrl: str) -> bool:
    """Same host + same first path segment counts as compatible.

    This is intentionally lenient: query params, fragments, and deep
    paths often differ across runs (different document IDs, timestamps)
    while the agent's intent is the same.
    """
    if not expectedUrl or not currentUrl:
        return True  # nothing to compare → don't block
    try:
        a, b = urlparse(expectedUrl), urlparse(currentUrl)
    except ValueError:
        return False
    if a.hostname != b.hostname:
        return False
    aSeg = a.path.strip("/").split("/", 1)[0] if a.path else ""
    bSeg = b.path.strip("/").split("/", 1)[0] if b.path else ""
    return aSeg == bSeg


@dataclass
class StateVerifier:
    """Decides whether a stored ActionNode is safe to replay right now.

    `phashThreshold`: max Hamming distance (bits) before the visual
    state is considered "different enough" to skip replay. 16 ≈ 25% of
    a 64-bit aHash, which empirically tracks "looks the same to a
    human" on most browser pages.
    """

    phashThreshold: int = DEFAULT_PHASH_HAMMING_THRESHOLD

    def verify(
        self,
        *,
        node: Any,  # ActionNode (kept loose to avoid circular import)
        currentUrl: str,
        currentScreenshot: bytes,
    ) -> VerificationResult:
        expectedUrl = getattr(node, "expected_url", "") or ""
        expectedPhash = getattr(node, "expected_phash", "") or ""

        # URL check
        urlOk = _urlsCompatible(expectedUrl, currentUrl)

        # Phash check
        phashDistance: int | None = None
        phashOk = True
        if expectedPhash and currentScreenshot:
            currentPhash = computeAverageHash(currentScreenshot)
            phashDistance = hammingDistance(expectedPhash, currentPhash)
            if phashDistance < 0:
                # Incompatible hash types or computation failed.
                # Fail open: don't block on phash issues — URL match suffices.
                phashOk = True
            else:
                phashOk = phashDistance <= self.phashThreshold

        safe = urlOk and phashOk
        reasonParts = []
        reasonParts.append(f"url={'ok' if urlOk else 'mismatch'}")
        if phashDistance is None:
            reasonParts.append("phash=skipped")
        else:
            reasonParts.append(f"phash={phashDistance}/{self.phashThreshold}")
        return VerificationResult(
            safe=safe,
            reason=" ".join(reasonParts),
            urlMatch=urlOk,
            phashDistance=phashDistance,
        )
