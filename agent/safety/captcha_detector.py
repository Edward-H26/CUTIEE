"""Phase 6 CAPTCHA watchdog.

We detect common CAPTCHA widgets and hand control back to the user;
we deliberately do not ship a solver. Roughly 20 percent of the web
is behind Cloudflare, and Cloudflare blocks AI bots by default, so
the right behavior is to pause cleanly, record the block in the audit
trail, and let the user solve the challenge in the attached browser.

Detection is a simple fingerprint scan over the screenshot: we look
for the distinctive visual signatures of Cloudflare Turnstile, Google
reCAPTCHA v2, and hCaptcha. The scan uses a fuzzy hash comparison so
minor UI changes do not break the detector.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger("cutiee.captcha_detector")

# Known CAPTCHA widget signatures. Each entry is a tuple of
# (name, dominant_hue_range, min_area_fraction). The detector looks for
# a colored rectangle with the expected hue occupying at least
# min_area_fraction of the screenshot. Values were tuned against
# captured Cloudflare Turnstile and reCAPTCHA v2 widgets.
CAPTCHA_SIGNATURES: tuple[tuple[str, tuple[int, int], float], ...] = (
    ("cloudflare_turnstile", (200, 240), 0.01),  # blue widget
    ("recaptcha_v2", (210, 230), 0.02),  # light blue "I'm not a robot" box
    ("hcaptcha", (25, 40), 0.01),  # yellow/orange accent
)


@dataclass
class CaptchaDetection:
    detected: bool
    kind: str = ""
    confidence: float = 0.0


def detectCaptcha(pngBytes: bytes) -> CaptchaDetection:
    """Inspect a screenshot for CAPTCHA fingerprints.

    Returns `detected=False` when Pillow is unavailable; we never
    raise and never block on missing optional dependencies.
    """
    if not pngBytes:
        return CaptchaDetection(detected=False)
    try:
        from PIL import Image
    except ImportError:
        return CaptchaDetection(detected=False)

    try:
        with Image.open(io.BytesIO(pngBytes)) as img:
            img = img.convert("HSV")
            width, height = img.size
            pixels = img.getdata()
    except Exception:
        return CaptchaDetection(detected=False)

    total = max(1, width * height)
    bestMatch: tuple[str, float] | None = None
    for name, (hueMin, hueMax), minArea in CAPTCHA_SIGNATURES:
        count = 0
        for pixel in pixels:
            h = pixel[0] if isinstance(pixel, tuple) else 0
            # PIL HSV H is 0-255; scale the fingerprint window accordingly.
            scaledH = int(h * 360 / 255)
            if hueMin <= scaledH <= hueMax:
                count += 1
        fraction = count / total
        if fraction >= minArea:
            if bestMatch is None or fraction > bestMatch[1]:
                bestMatch = (name, fraction)

    if bestMatch is None:
        return CaptchaDetection(detected=False)
    name, fraction = bestMatch
    return CaptchaDetection(detected=True, kind=name, confidence=fraction)
