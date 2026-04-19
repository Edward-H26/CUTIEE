"""Playwright wrapper that exposes the verbs CUTIEE actions need.

The controller is async-friendly so it can be driven from the Django request
loop via Celery / asyncio later. It owns a single browser context per task so
that `storage_state` (cookies, localStorage) can be saved and reused across
runs.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from agent.browser.dom_extractor import DOMState, extractDomState
from agent.harness.state import Action, ActionType


@dataclass
class StepResult:
    success: bool
    detail: str = ""
    durationMs: int = 0
    domState: DOMState | None = None


@dataclass
class BrowserController:
    headless: bool = True
    storageStatePath: str | None = None
    defaultTimeoutMs: int = 7000
    _playwright: Any = field(default = None, init = False, repr = False)
    _browser: Any = field(default = None, init = False, repr = False)
    _context: Any = field(default = None, init = False, repr = False)
    _page: Any = field(default = None, init = False, repr = False)

    async def start(self) -> None:
        if self._page is not None:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless = self.headless)
        contextArgs: dict[str, Any] = {"viewport": {"width": 1280, "height": 800}}
        if self.storageStatePath:
            contextArgs["storage_state"] = self.storageStatePath
        self._context = await self._browser.new_context(**contextArgs)
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.defaultTimeoutMs)

    async def stop(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        finally:
            if self._browser is not None:
                await self._browser.close()
            if self._playwright is not None:
                await self._playwright.stop()
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    @property
    def page(self) -> Any:
        if self._page is None:
            raise RuntimeError("BrowserController.start() must be called before .page is accessed.")
        return self._page

    async def observe(self) -> DOMState:
        await self._page.wait_for_load_state("domcontentloaded", timeout = self.defaultTimeoutMs)
        return await extractDomState(self._page)

    async def execute(self, action: Action) -> StepResult:
        loop = asyncio.get_event_loop()
        startedAt = loop.time()
        try:
            if action.type == ActionType.NAVIGATE:
                await self._page.goto(action.target)
            elif action.type == ActionType.CLICK:
                await self._page.locator(action.target).first.click()
            elif action.type == ActionType.FILL:
                await self._page.locator(action.target).first.fill(action.value or "")
            elif action.type == ActionType.SELECT:
                await self._page.locator(action.target).first.select_option(action.value or "")
            elif action.type == ActionType.PRESS:
                await self._page.keyboard.press(action.value or action.target)
            elif action.type == ActionType.SCROLL:
                pixels = int(action.value) if action.value else 500
                await self._page.mouse.wheel(0, pixels)
            elif action.type == ActionType.WAIT:
                seconds = float(action.value) if action.value else 1.0
                await asyncio.sleep(seconds)
            elif action.type in (ActionType.FINISH, ActionType.APPROVE):
                pass
            else:
                return StepResult(success = False, detail = f"unknown action: {action.type}")
        except Exception as exc:
            elapsed = int((loop.time() - startedAt) * 1000)
            return StepResult(success = False, detail = repr(exc), durationMs = elapsed)

        elapsed = int((loop.time() - startedAt) * 1000)
        return StepResult(success = True, durationMs = elapsed)

    async def saveStorageState(self, path: str) -> None:
        await self._context.storage_state(path = path)


@dataclass
class StubBrowserController:
    """Synchronous stand-in used by Phase 1 tests + the Django demo path.

    Implements the same observe/execute surface but without a real browser.
    The Django services layer instantiates this when no Playwright runtime is
    available (e.g., on Render's web tier without browser binaries) so the UI
    flow stays end-to-end testable from the orchestrator down.
    """
    scriptedDom: DOMState | None = None
    log: list[Action] = field(default_factory = list)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def observe(self) -> DOMState:
        if self.scriptedDom is None:
            return DOMState(url = "stub://blank", title = "blank", markdown = "(stub)")
        return self.scriptedDom

    async def execute(self, action: Action) -> StepResult:
        self.log.append(action)
        return StepResult(success = True, durationMs = 1)

    async def saveStorageState(self, path: str) -> None:
        del path
        return None
