"""Playwright wrapper that exposes the verbs CUTIEE actions need.

The controller is async-friendly so it can be driven from the Django request
loop via Celery / asyncio later. It owns a single browser context per task so
that `storage_state` (cookies, localStorage) can be saved and reused across
runs.

Default posture is **headed** (`headless=False`). Computer Use is a
spectator feature; if the user can't see the agent operating, the demo
loses its value and silent action failures look indistinguishable from
success. Override with `CUTIEE_BROWSER_HEADLESS=1` for CI / smoke tests.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.harness.state import Action, ActionType


@dataclass
class StepResult:
    success: bool
    detail: str = ""
    durationMs: int = 0


@dataclass
class BrowserController:
    headless: bool = False
    storageStatePath: str | None = None
    defaultTimeoutMs: int = 7000
    slowMoMs: int = 0
    viewportWidth: int = 1280
    viewportHeight: int = 800
    cdpUrl: str | None = None
    _playwright: Any = field(default = None, init = False, repr = False)
    _browser: Any = field(default = None, init = False, repr = False)
    _context: Any = field(default = None, init = False, repr = False)
    _page: Any = field(default = None, init = False, repr = False)
    _attachedToExisting: bool = field(default = False, init = False, repr = False)

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
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdpUrl)
            existing = self._browser.contexts
            self._context = existing[0] if existing else await self._browser.new_context()
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
            self._attachedToExisting = True
            self._page.set_default_timeout(self.defaultTimeoutMs)
            return

        launchArgs: list[str] = []
        if not self.headless:
            launchArgs.append("--start-maximized")
        self._browser = await self._playwright.chromium.launch(
            headless = self.headless,
            slow_mo = self.slowMoMs,
            args = launchArgs,
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
                await self._page.goto(action.target)
            elif action.type == ActionType.WAIT:
                seconds = float(action.value) if action.value else 1.0
                await asyncio.sleep(seconds)
            elif action.type == ActionType.CLICK_AT:
                if action.coordinate is None:
                    return StepResult(success = False, detail = "click_at requires coordinate")
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
                    return StepResult(success = False, detail = "key_combo requires keys")
                # Playwright accepts "Control+A" style combos in keyboard.press.
                await self._page.keyboard.press("+".join(keys))
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
                return StepResult(success = False, detail = f"unknown action: {action.type}")
        except Exception as exc:
            elapsed = int((loop.time() - startedAt) * 1000)
            return StepResult(success = False, detail = repr(exc), durationMs = elapsed)

        elapsed = int((loop.time() - startedAt) * 1000)
        return StepResult(success = True, durationMs = elapsed)

    async def captureScreenshot(self) -> bytes:
        return await self._page.screenshot(type = "png", full_page = False)

    async def currentUrl(self) -> str:
        return self._page.url

    async def saveStorageState(self, path: str) -> None:
        await self._context.storage_state(path = path)


@dataclass
class StubBrowserController:
    """No-op browser stand-in for tests + Render's web tier (no chromium binary).

    Implements the same start/stop/execute/captureScreenshot/currentUrl surface
    that ComputerUseRunner expects, but never actually launches anything.
    Returns a 1×1 transparent PNG for screenshots so the runner's screenshot
    sink path stays exercised end-to-end without a real browser.
    """
    log: list[Action] = field(default_factory = list)
    fakeUrl: str = "stub://blank"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def execute(self, action: Action) -> StepResult:
        self.log.append(action)
        return StepResult(success = True, durationMs = 1)

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


def browserFromEnv(*, defaultHeadless: bool = False, domain: str = "") -> "BrowserController":
    """Build a BrowserController from CUTIEE_BROWSER_* env vars.

    Reads:
      - CUTIEE_BROWSER_HEADLESS (default: defaultHeadless)
      - CUTIEE_STORAGE_STATE_PATH (path to Playwright storage_state.json)
      - CUTIEE_BROWSER_SLOW_MO_MS (delay between actions for visibility)
      - CUTIEE_BROWSER_CDP_URL (Chrome DevTools attach URL, e.g. http://localhost:9222)

    `domain` (optional): used to look for a domain-scoped storage_state file
    at `data/storage_state/<domain>.json` first, falling back to the
    global path. This avoids leaking google.com cookies into github.com runs.
    """
    from agent.harness.env_utils import envBool, envInt, envStr

    headless = envBool("CUTIEE_BROWSER_HEADLESS", defaultHeadless)
    slowMo = envInt("CUTIEE_BROWSER_SLOW_MO_MS", 0)
    cdpUrl = envStr("CUTIEE_BROWSER_CDP_URL") or None
    storage = _resolveStorageStatePath(domain)
    return BrowserController(
        headless = headless,
        storageStatePath = storage,
        slowMoMs = slowMo,
        cdpUrl = cdpUrl,
    )


def _resolveStorageStatePath(domain: str) -> str | None:
    """Pick the most-specific storage_state file that exists.

    Order: data/storage_state/<domain>.json → CUTIEE_STORAGE_STATE_PATH.
    Returning None means "fresh cookie jar".
    """
    if domain:
        scoped = Path("data/storage_state") / f"{domain}.json"
        if scoped.exists():
            return str(scoped)
    fallback = os.environ.get("CUTIEE_STORAGE_STATE_PATH")
    if fallback and Path(fallback).exists():
        return fallback
    return None
