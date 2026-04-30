"""Unit tests for the shared HTTP query-param helpers."""

from __future__ import annotations

from apps.common.query_utils import safeInt


def test_safeIntReturnsDefaultOnNone():
    assert safeInt(None, default=14) == 14


def test_safeIntReturnsDefaultOnEmptyString():
    assert safeInt("", default=7) == 7


def test_safeIntReturnsDefaultOnNonNumeric():
    assert safeInt("abc", default=5) == 5


def test_safeIntParsesValidInteger():
    assert safeInt("42", default=0) == 42


def test_safeIntClampsBelowMinimum():
    assert safeInt("-3", default=0, minimum=0) == 0


def test_safeIntClampsAboveMaximum():
    assert safeInt("999", default=0, maximum=100) == 100


def test_safeIntKeepsValueInsideWindow():
    assert safeInt("50", default=0, minimum=1, maximum=100) == 50
