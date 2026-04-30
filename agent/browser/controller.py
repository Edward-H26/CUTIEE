"""Playwright wrapper that exposes the verbs CUTIEE actions need.

The controller is async-friendly so it can be driven from the Django request
loop via Celery / asyncio later. It owns a single browser context per task so
that `storage_state` (cookies, localStorage) can be saved and reused across
runs.

Default posture is **headed** (`headless=False`). Computer Use is a
spectator feature; if the user can't see the agent operating, the demo
loses its value and silent action failures look indistinguishable from
success. Override with `CUTIEE_BROWSER_HEADLESS=1` for CI / smoke tests.

`BrowserControllerProtocol` formalizes the contract both `BrowserController`
(Playwright-backed, real browser) and `StubBrowserController` (no-op, for
tests and tiers without Chromium) satisfy. The runner accepts anything
satisfying the Protocol, which eliminates the prior Pyright complaints
about passing `StubBrowserController` where `BrowserController` was typed.
"""

from __future__ import annotations

import asyncio
import os
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..harness.url_safety import sanitizeNavigationUrl
from ..harness.state import Action, ActionType
from ..safety.injection_guard import stripUrlFragment, urlFragmentsAllowed


@dataclass
class StepResult:
    success: bool
    detail: str = ""
    durationMs: int = 0


@runtime_checkable
class BrowserControllerProtocol(Protocol):
    """Contract that every browser controller in CUTIEE must honor.

    Satisfied by `BrowserController` (Playwright real browser) and
    `StubBrowserController` (no-op for tests). The runner accepts
    anything that matches this shape, which keeps `StubBrowserController`
    usable where `BrowserController` was previously typed.
    """

    cdpUrl: str | None

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def execute(self, action: Action) -> StepResult: ...
    async def captureScreenshot(self) -> bytes: ...
    async def currentUrl(self) -> str: ...
    async def saveStorageState(self, path: str) -> None: ...


@dataclass
class BrowserController:
    headless: bool = False
    storageStatePath: str | None = None
    defaultTimeoutMs: int = 7000
    slowMoMs: int = 0
    viewportWidth: int = 1280
    viewportHeight: int = 800
    cdpUrl: str | None = None
    # Phase 14 screenshot compression: downscale-and-reencode knobs.
    # quality (1-100) maps to PNG/JPEG quality; maxWidth downscales the
    # longer edge before encoding. Both default to no-op values that
    # keep the pre-phase behavior (PNG at native viewport).
    screenshotQuality: int = 90
    screenshotMaxWidth: int = 1280
    _playwright: Any = field(default=None, init=False, repr=False)
    _browser: Any = field(default=None, init=False, repr=False)
    _context: Any = field(default=None, init=False, repr=False)
    _page: Any = field(default=None, init=False, repr=False)
    _attachedToExisting: bool = field(default=False, init=False, repr=False)

    async def start(self) -> None:
        if self._page is not None:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        # CDP attach mode: drive an already-running Chrome instance instead
        # of launching a fresh chromium. The user starts Chrome once with
        # `--remote-debugging-port=9222` and the agent inherits all real
        # cookies / extensions / open tabs. Strictly more powerful than
        # storage_state because it survives 2FA challenges and lives next
        # to the user's actual browsing.
        if self.cdpUrl:
            # Phase 9 CDP tab fencing: attach to the user's running Chrome
            # for its auth state, but always open a fresh page for the
            # agent. Previously we inherited `contexts[0].pages[0]`, which
            # meant the agent could read and act on whichever unrelated
            # tab the user had focused. A fresh page isolates the agent's
            # work from the user's other browsing.
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdpUrl)
            existing = self._browser.contexts
            self._context = existing[0] if existing else await self._browser.new_context()
            self._page = await self._context.new_page()
            self._attachedToExisting = True
            self._page.set_default_timeout(self.defaultTimeoutMs)
            return

        launchArgs: list[str] = []
        if not self.headless:
            launchArgs.append("--start-maximized")
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slowMoMs,
            args=launchArgs,
        )
        contextArgs: dict[str, Any] = {
            "viewport": {"width": self.viewportWidth, "height": self.viewportHeight},
        }
        # Reuse a previously-saved storage_state.json when present so the
        # agent is already signed into Google / GitHub / etc. on launch.
        # Without this, every CU run starts from a cold cookie jar and gets
        # bounced to a login page that the agent then "successfully" clicks
        # around on, producing OK steps with no real-world effect.
        if self.storageStatePath and Path(self.storageStatePath).exists():
            contextArgs["storage_state"] = self.storageStatePath
        self._context = await self._browser.new_context(**contextArgs)
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.defaultTimeoutMs)

    async def stop(self) -> None:
        try:
            # In CDP-attach mode the context belongs to the user's real Chrome.
            # Closing it would kill their open tabs, so we just detach.
            if self._context is not None and not self._attachedToExisting:
                await self._context.close()
        finally:
            if self._browser is not None:
                if self._attachedToExisting:
                    # close() on a CDP-attached browser disconnects without
                    # killing the upstream Chrome process.
                    pass
                await self._browser.close()
            if self._playwright is not None:
                await self._playwright.stop()
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self._attachedToExisting = False

    @property
    def page(self) -> Any:
        if self._page is None:
            raise RuntimeError("BrowserController.start() must be called before .page is accessed.")
        return self._page

    async def execute(self, action: Action) -> StepResult:
        loop = asyncio.get_event_loop()
        startedAt = loop.time()
        try:
            if action.type == ActionType.NAVIGATE:
                target = action.target
                if not urlFragmentsAllowed():
                    target = stripUrlFragment(target)
                sanitizedTarget, error = sanitizeNavigationUrl(
                    target,
                    allowPrivateHosts=_allowPrivateNavigationTargets(),
                )
                if sanitizedTarget is None:
                    return StepResult(success=False, detail=error)
                action.target = sanitizedTarget
                await self._page.goto(sanitizedTarget)
            elif action.type == ActionType.WAIT:
                seconds = float(action.value) if action.value else 1.0
                await asyncio.sleep(seconds)
            elif action.type == ActionType.CLICK_AT:
                if action.coordinate is None:
                    return StepResult(success=False, detail="click_at requires coordinate")
                x, y = action.coordinate
                await self._page.mouse.click(x, y)
            elif action.type == ActionType.TYPE_AT:
                if action.coordinate is not None:
                    x, y = action.coordinate
                    await self._page.mouse.click(x, y)
                await self._page.keyboard.type(action.value or "")
            elif action.type == ActionType.KEY_COMBO:
                keys = action.keys or ([action.value] if action.value else [])
                if not keys:
                    return StepResult(success=False, detail="key_combo requires keys")
                # Playwright requires its own canonical key names (ArrowUp,
                # PageDown, etc.). Gemini emits informal aliases like "up"
                # or "page_down"; normalize them here so the press succeeds
                # instead of throwing `Unknown key` and burning a retry.
                normalized = [_normalizePlaywrightKey(k) for k in keys]
                await self._page.keyboard.press("+".join(normalized))
            elif action.type == ActionType.SCROLL_AT:
                if action.coordinate is not None:
                    await self._page.mouse.move(*action.coordinate)
                await self._page.mouse.wheel(action.scrollDx, action.scrollDy)
            elif action.type == ActionType.OPEN_BROWSER:
                # The browser is already open; treat as a no-op so the loop progresses.
                pass
            elif action.type in (ActionType.FINISH, ActionType.APPROVE):
                pass
            else:
                return StepResult(success=False, detail=f"unknown action: {action.type}")
        except Exception as exc:
            elapsed = int((loop.time() - startedAt) * 1000)
            return StepResult(success=False, detail=repr(exc), durationMs=elapsed)

        elapsed = int((loop.time() - startedAt) * 1000)
        return StepResult(success=True, durationMs=elapsed)

    async def captureScreenshot(self) -> bytes:
        raw = await self._page.screenshot(type="png", full_page=False)
        return _compressScreenshot(raw, self.screenshotQuality, self.screenshotMaxWidth)

    async def currentUrl(self) -> str:
        return self._page.url

    async def saveStorageState(self, path: str) -> None:
        await self._context.storage_state(path=path)


@dataclass
class StubBrowserController:
    """No-op browser stand-in that satisfies `BrowserControllerProtocol`.

    Used for unit tests and tiers without Chromium installed. Implements
    the full start/stop/execute/captureScreenshot/currentUrl surface but
    never actually launches anything. Returns a 1x1 transparent PNG for
    screenshots so the runner's screenshot sink path stays exercised
    end-to-end without a real browser.
    """

    log: list[Action] = field(default_factory=list)
    fakeUrl: str = "stub://blank"
    # Protocol-shaped field so `isinstance(stub, BrowserControllerProtocol)`
    # passes without callers needing to care about the underlying impl.
    cdpUrl: str | None = None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def execute(self, action: Action) -> StepResult:
        self.log.append(action)
        return StepResult(success=True, durationMs=1)

    async def captureScreenshot(self) -> bytes:
        # Smallest valid PNG: 1x1 transparent pixel. Lets the screenshot sink
        # path execute without dragging in a real chromium.
        import base64

        return base64.b64decode(
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )

    async def currentUrl(self) -> str:
        return self.fakeUrl

    async def saveStorageState(self, path: str) -> None:
        del path
        return None


def _compressScreenshot(pngBytes: bytes, quality: int, maxWidth: int) -> bytes:
    """Optionally downscale and re-encode a screenshot.

    Phase 14 trades a small quality loss for meaningful token savings:
    models charge per pixel of the decoded image, so shrinking from
    1920 down to 1280 cuts ~40 percent of input image tokens. Behavior
    stays a no-op when Pillow is not installed or when the source is
    already within the limits; we never raise a runtime error here.
    """
    if quality >= 100 and maxWidth <= 0:
        return pngBytes
    try:
        import io

        from PIL import Image
    except ImportError:
        return pngBytes

    try:
        with Image.open(io.BytesIO(pngBytes)) as img:
            width, height = img.size
            if maxWidth > 0 and width > maxWidth:
                scale = maxWidth / float(width)
                newSize = (maxWidth, max(1, int(height * scale)))
                resample = getattr(Image, "Resampling", Image).LANCZOS  # type: ignore[attr-defined]
                img = img.resize(newSize, resample=resample)
            buffer = io.BytesIO()
            img.save(buffer, format="PNG", optimize=True, compress_level=9)
            return buffer.getvalue()
    except Exception:
        return pngBytes


def _allowPrivateNavigationTargets() -> bool:
    return os.environ.get("CUTIEE_ENV") == "local"


# RFC 1035 hostname charset: letters, digits, hyphens, dots only. No slashes,
# no backslashes, no dot-dot, no leading/trailing dots or hyphens. Used to
# guard against path traversal when `domain` is derived from user-supplied URLs.
_VALID_DOMAIN_RE = _re.compile(r"^(?!-)[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,253}[a-zA-Z0-9])?$")


def _isSafeDomain(domain: str) -> bool:
    if not domain or len(domain) > 253:
        return False
    if ".." in domain or domain.startswith(".") or domain.endswith("."):
        return False
    return bool(_VALID_DOMAIN_RE.match(domain))


def browserFromEnv(
    *,
    defaultHeadless: bool = False,
    domain: str = "",
    userId: str = "",
) -> "BrowserController":
    """Build a BrowserController from CUTIEE_BROWSER_* env vars.

    Reads:
      - CUTIEE_BROWSER_HEADLESS (default: defaultHeadless)
      - CUTIEE_STORAGE_STATE_PATH (path to Playwright storage_state.json)
      - CUTIEE_BROWSER_SLOW_MO_MS (delay between actions for visibility)
      - CUTIEE_BROWSER_CDP_URL (Chrome DevTools attach URL, e.g. http://localhost:9222)

    `domain` and `userId` (both optional): used to look for a per-user,
    per-domain storage_state at `data/storage_state/<userId>/<domain>.json`
    first, then `data/storage_state/<domain>.json` (legacy global path),
    then `CUTIEE_STORAGE_STATE_PATH`. The user_id scoping prevents one
    user's auth cookies from leaking into another user's CU run.
    """
    from agent.harness.env_utils import envBool, envInt, envStr

    headless = envBool("CUTIEE_BROWSER_HEADLESS", defaultHeadless)
    slowMo = envInt("CUTIEE_BROWSER_SLOW_MO_MS", 0)
    cdpUrl = envStr("CUTIEE_BROWSER_CDP_URL") or None
    storage = _resolveStorageStatePath(domain, userId)
    return BrowserController(
        headless=headless,
        storageStatePath=storage,
        slowMoMs=slowMo,
        cdpUrl=cdpUrl,
    )


def _resolveStorageStatePath(domain: str, userId: str = "") -> str | None:
    """Pick the most-specific storage_state file that exists.

    Lookup order:
      1. `data/storage_state/<userId>/<domain>.json`  (per-user, per-domain)
      2. `data/storage_state/<domain>.json`           (legacy global per-domain)
      3. `CUTIEE_STORAGE_STATE_PATH`                  (env-configured default)

    `domain` is validated against an RFC 1035 hostname regex before being
    used in a filesystem path so user-supplied URLs can't trigger path
    traversal. Returning None means "fresh cookie jar".
    """
    if domain and not _isSafeDomain(domain):
        # Defensive: refuse to construct a path from an unsafe domain string.
        # The agent will run with a fresh cookie jar instead.
        domain = ""

    safeUserId = ""
    if userId:
        # User IDs are normally numeric strings (Django pk) but be defensive:
        # strip anything that isn't alphanumeric / underscore / hyphen.
        safeUserId = _re.sub(r"[^A-Za-z0-9_-]", "", userId)[:64]

    if domain:
        if safeUserId:
            perUser = Path("data/storage_state") / safeUserId / f"{domain}.json"
            if perUser.exists():
                return str(perUser)
        scoped = Path("data/storage_state") / f"{domain}.json"
        if scoped.exists():
            return str(scoped)
    fallback = os.environ.get("CUTIEE_STORAGE_STATE_PATH")
    if fallback and Path(fallback).exists():
        return fallback
    return None


# Gemini ComputerUse emits informal key names ("up", "page_down", "ctrl");
# Playwright requires its canonical names. Map the common aliases so the
# `keyboard.press` call succeeds instead of raising `Unknown key`.
_PLAYWRIGHT_KEY_ALIASES = {
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "esc": "Escape",
    "del": "Delete",
    "ins": "Insert",
    "page_up": "PageUp",
    "page_down": "PageDown",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "ctrl": "Control",
    "cmd": "Meta",
    "command": "Meta",
    "win": "Meta",
    "return": "Enter",
    "space": " ",
}


def _normalizePlaywrightKey(key: str) -> str:
    """Normalize a Gemini-emitted key name to Playwright's canonical form.

    Already-canonical keys (`Enter`, `Tab`, `ArrowUp`, single chars, F1)
    pass through untouched. Unknown keys also pass through so Playwright's
    own error message surfaces if Gemini hallucinates something exotic.
    """
    if not key:
        return key
    lower = key.strip().lower()
    if lower in _PLAYWRIGHT_KEY_ALIASES:
        return _PLAYWRIGHT_KEY_ALIASES[lower]
    return key
