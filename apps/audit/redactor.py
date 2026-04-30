"""Phase 8 screenshot redaction.

Before a screenshot enters the audit pipeline we blur or black out
regions that commonly contain credentials: password input fields, SSN
and CVV label regions. The unredacted bytes stay only in the per-step
local variable and are garbage-collected at the end of the step.

The redaction pipeline is intentionally conservative. If Pillow is not
installed or if we cannot compute any redaction regions, we return the
original bytes and rely on Phase 10 reflector scrubbing to catch
credentials in bullet content.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger("cutiee.redactor")

CREDENTIAL_LABEL_RE = re.compile(
    r"\b(password|ssn|credit\s*card|cvv|cvc|pin|secret|token|api[_-]?key)\b",
    re.IGNORECASE,
)


@dataclass
class RedactionRegion:
    """A rectangle in screen coordinates to mask before persistence."""

    x: int
    y: int
    width: int
    height: int
    reason: str = ""


class DomProbe(Protocol):
    """Optional DOM inspector that returns bounding boxes to redact.

    Phase 8 expects a probe that returns password input bboxes and any
    labelled input whose visible text matches a credential keyword. The
    runner wires a real Playwright-backed probe; tests can pass a stub.
    """

    def findCredentialRegions(self) -> list[RedactionRegion]: ...


def redactScreenshot(
    pngBytes: bytes,
    regions: list[RedactionRegion] | None = None,
) -> bytes:
    """Mask the given regions with an opaque black rectangle.

    When Pillow is absent or regions are empty, we return the input
    unchanged. We never raise from this path because a failed
    redaction must not prevent the run from making progress; Phase 10
    catches credential leaks downstream in the bullet content layer.
    """
    if not pngBytes:
        return pngBytes
    if not regions:
        return pngBytes
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return pngBytes

    try:
        with Image.open(io.BytesIO(pngBytes)) as img:
            img = img.convert("RGB")
            draw = ImageDraw.Draw(img)
            for region in regions:
                box = (
                    region.x,
                    region.y,
                    region.x + region.width,
                    region.y + region.height,
                )
                draw.rectangle(box, fill=(0, 0, 0))
            buffer = io.BytesIO()
            img.save(buffer, format="PNG", optimize=True, compress_level=9)
            return buffer.getvalue()
    except Exception:
        logger.warning("Screenshot redaction failed; returning original bytes", exc_info=True)
        return pngBytes


def regionsFromTexts(
    texts: list[tuple[str, RedactionRegion]],
) -> list[RedactionRegion]:
    """Filter a list of (label_text, bbox) tuples down to credential regions.

    Passed a list of text labels next to their bounding boxes, this
    returns only the regions whose label matches a credential keyword.
    Intended to be fed from the Phase 8 DOM probe.
    """
    out: list[RedactionRegion] = []
    for label, region in texts:
        if CREDENTIAL_LABEL_RE.search(label):
            out.append(
                RedactionRegion(
                    x=region.x,
                    y=region.y,
                    width=region.width,
                    height=region.height,
                    reason=f"label:{label}",
                )
            )
    return out


# Selectors that reliably indicate credential inputs. The runner's
# redactor hook calls `playwrightDomRedactor(browser, screenshot)` and
# uses the returned regions to paint over the screenshot before it
# reaches Neo4j. Selectors are conservative: we only mask obvious
# cases (password-type inputs, autocomplete hints for payment data)
# so legitimate form fields are not blanked out.
_CREDENTIAL_SELECTORS: tuple[str, ...] = (
    "input[type='password']",
    "input[autocomplete='current-password']",
    "input[autocomplete='new-password']",
    "input[autocomplete='cc-number']",
    "input[autocomplete='cc-csc']",
    "input[autocomplete='cc-exp']",
    "input[autocomplete='one-time-code']",
    "input[name*='password' i]",
    "input[name*='ssn' i]",
    "input[name*='cvv' i]",
    "input[name*='cvc' i]",
    "input[aria-label*='password' i]",
    "input[aria-label*='credit card' i]",
    "input[aria-label*='social security' i]",
)


async def playwrightDomRedactor(
    browser: Any,
    screenshotBytes: bytes,
) -> list[RedactionRegion]:
    """Phase 8 concrete DOM probe backed by Playwright.

    Inspects the currently-active Playwright page for credential
    inputs via the selector list above, returning their bounding
    boxes as `RedactionRegion`s. The runner uses those regions to
    mask the screenshot before it enters the audit sink.

    Failure-safe in four ways:
      1. If `browser.page` is None (stub, Playwright not started),
         returns an empty list. Zero regions means `redactScreenshot`
         returns the screenshot unchanged.
      2. If any selector raises (element detached, page navigating),
         the individual selector is skipped; the probe keeps going.
      3. If `bounding_box()` returns None (element off-screen,
         display:none), the region is skipped.
      4. The top-level try/except catches any unexpected error and
         returns an empty list so the audit pipeline never aborts
         because the redactor failed.

    The screenshot parameter is intentionally unused today; it is kept
    in the signature so a future probe can cross-check the DOM result
    against OCR confidence without changing call sites.
    """
    del screenshotBytes  # reserved for future OCR-backed heuristics
    page = getattr(browser, "page", None) if browser is not None else None
    if page is None:
        return []
    regions: list[RedactionRegion] = []
    try:
        for selector in _CREDENTIAL_SELECTORS:
            try:
                elements = await page.query_selector_all(selector)
            except Exception:  # noqa: BLE001 - selector failures never block the run
                logger.debug("redactor selector failed: %s", selector, exc_info=True)
                continue
            for element in elements:
                try:
                    box = await element.bounding_box()
                except Exception:  # noqa: BLE001
                    continue
                if not box:
                    continue
                regions.append(
                    RedactionRegion(
                        x=int(box["x"]),
                        y=int(box["y"]),
                        width=max(1, int(box["width"])),
                        height=max(1, int(box["height"])),
                        reason=f"selector:{selector}",
                    )
                )
    except Exception:  # noqa: BLE001 - never crash the audit pipeline
        logger.debug("playwrightDomRedactor top-level failure", exc_info=True)
        return []
    return regions
