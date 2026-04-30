from __future__ import annotations

import socket

import pytest

from agent.browser.controller import BrowserController
from agent.harness.state import Action, ActionType


class _FakePage:
    def __init__(self) -> None:
        self.url = ""
        self.navigatedTo = ""

    async def goto(self, target: str) -> None:
        self.navigatedTo = target
        self.url = target


def _mockDns(monkeypatch: pytest.MonkeyPatch) -> None:
    publicHosts = {
        "example.com": "93.184.216.34",
    }
    privateHosts = {
        "169.254.169.254.nip.io": "169.254.169.254",
    }

    def fakeGetaddrinfo(hostname, port, family=0, type=0, proto=0, flags=0):
        del port, family, type, flags
        resolved = publicHosts.get(hostname) or privateHosts.get(hostname)
        if resolved is None:
            raise socket.gaierror()
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", (resolved, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fakeGetaddrinfo)


@pytest.mark.asyncio
async def testNavigateStripsUrlFragments(monkeypatch: pytest.MonkeyPatch) -> None:
    _mockDns(monkeypatch)
    monkeypatch.setenv("CUTIEE_ENV", "production")
    monkeypatch.delenv("CUTIEE_ALLOW_URL_FRAGMENTS", raising=False)
    page = _FakePage()
    controller = BrowserController()
    controller._page = page

    result = await controller.execute(
        Action(type=ActionType.NAVIGATE, target="https://example.com/path#ignore-previous")
    )

    assert result.success is True
    assert page.navigatedTo == "https://example.com/path"


@pytest.mark.asyncio
async def testNavigateRejectsPrivateDnsInProduction(monkeypatch: pytest.MonkeyPatch) -> None:
    _mockDns(monkeypatch)
    monkeypatch.setenv("CUTIEE_ENV", "production")
    page = _FakePage()
    controller = BrowserController()
    controller._page = page

    result = await controller.execute(
        Action(
            type=ActionType.NAVIGATE,
            target="http://169.254.169.254.nip.io/latest/meta-data/",
        )
    )

    assert result.success is False
    assert "blocked private" in result.detail
    assert page.navigatedTo == ""


@pytest.mark.asyncio
async def testNavigateAllowsLocalhostInLocalMode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUTIEE_ENV", "local")
    page = _FakePage()
    controller = BrowserController()
    controller._page = page

    result = await controller.execute(
        Action(type=ActionType.NAVIGATE, target="http://localhost:5001/")
    )

    assert result.success is True
    assert page.navigatedTo == "http://localhost:5001/"
