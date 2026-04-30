"""Unit tests for the shared URL helper."""

from __future__ import annotations

from agent.harness.url_utils import hostFromUrl


def test_hostFromUrlReturnsEmptyForFalsy():
    assert hostFromUrl("") == ""


def test_hostFromUrlReturnsEmptyForSchemeless():
    assert hostFromUrl("no-scheme-here") == ""


def test_hostFromUrlStripsScheme():
    assert hostFromUrl("https://docs.google.com/spreadsheets/abc") == "docs.google.com"


def test_hostFromUrlStripsPort():
    # The browser controller's _isSafeDomain rejects ":"; keeping port
    # here would silently break per-site storage-state lookup.
    assert hostFromUrl("http://localhost:8080/demo") == "localhost"


def test_hostFromUrlStripsUserInfo():
    assert hostFromUrl("https://user:pw@example.com/path") == "example.com"


def test_hostFromUrlIgnoresQueryAndFragment():
    assert hostFromUrl("https://example.com?a=1#frag") == "example.com"
    assert hostFromUrl("https://example.com/?a=1") == "example.com"
