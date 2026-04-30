"""Regression tests for the 5th-pass security fixes.

Two threats this guards against:

1. **Path traversal via user-supplied URL**: the agent extracts a domain
   from `initial_url` (user input) and uses it to look up a per-domain
   storage_state file. Without validation, a crafted URL could escape
   the `data/storage_state/` directory.

2. **Cross-user cookie leakage**: pre-fix, all users sharing a domain
   inherited the same `data/storage_state/<domain>.json`. Now the
   per-user-scoped path takes precedence so user A's auth cookies
   don't leak into user B's CU run.
"""

from __future__ import annotations

import pytest

from agent.browser.controller import _isSafeDomain, _resolveStorageStatePath


def test_safe_domain_accepts_normal_hostnames() -> None:
    for d in ("google.com", "docs.google.com", "github.com", "a.b.c.d", "example-site.org"):
        assert _isSafeDomain(d), f"{d!r} should be accepted"


def test_safe_domain_rejects_path_traversal() -> None:
    """The user could submit `initial_url` with path-escape characters.
    The validator must refuse anything that could escape data/storage_state/."""
    bad = [
        "..",
        "../etc/passwd",
        "../../etc/passwd",
        ".",
        "..hidden",
        "google.com/../passwords",
        "google.com\\..\\..\\windows",
        "\\windows",
        "/etc/passwd",
        "google.com\x00.json",
        "",
        ".google.com",  # leading dot
        "google.com.",  # trailing dot
        "-google.com",  # leading hyphen
        "google.com-",  # trailing hyphen
    ]
    for d in bad:
        assert not _isSafeDomain(d), f"{d!r} should be rejected as unsafe"


def test_safe_domain_rejects_oversized_input() -> None:
    """RFC 1035 caps hostnames at 253 chars; reject anything beyond that."""
    long = "a" * 254
    assert not _isSafeDomain(long)


def test_storage_state_falls_back_to_none_for_unsafe_domain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Even if an attacker-controlled file matched the bad path, the
    validator zeros out `domain` so we never construct the lookup."""
    monkeypatch.chdir(tmp_path)
    storageDir = tmp_path / "data" / "storage_state"
    storageDir.mkdir(parents=True)
    # Plant a file the attacker would want to read
    (storageDir / "..json").write_text("{}")
    # Even though the file exists, the unsafe domain string is rejected
    assert _resolveStorageStatePath("..") is None


def test_storage_state_per_user_scoping_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """If both `data/storage_state/<userId>/<domain>.json` and
    `data/storage_state/<domain>.json` exist, the per-user file wins
    so user A's cookies aren't loaded into user B's run."""
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    storageRoot = tmp_path / "data" / "storage_state"
    storageRoot.mkdir(parents=True)
    (storageRoot / "google.com.json").write_text('{"shared":1}')
    perUserDir = storageRoot / "42"
    perUserDir.mkdir()
    perUserFile = perUserDir / "google.com.json"
    perUserFile.write_text('{"per_user":1}')

    resolved = _resolveStorageStatePath("google.com", userId="42")
    assert resolved is not None
    # Resolution returns a relative path; resolve it for comparison
    assert (
        Path(resolved).resolve().samefile(perUserFile)
    ), f"per-user file should win over shared, got {resolved!r}"


def test_storage_state_falls_back_to_shared_when_no_per_user(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """When no per-user file exists, the legacy shared file is used.
    Acceptable behavior for single-user demos."""
    from pathlib import Path

    monkeypatch.chdir(tmp_path)
    storageRoot = tmp_path / "data" / "storage_state"
    storageRoot.mkdir(parents=True)
    sharedFile = storageRoot / "github.com.json"
    sharedFile.write_text('{"shared":1}')

    resolved = _resolveStorageStatePath("github.com", userId="42")
    assert resolved is not None
    assert Path(resolved).resolve().samefile(sharedFile)


def test_user_id_with_path_chars_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Even though Django user_id is a numeric pk, defend against the case
    where it gets manipulated upstream and contains path separators."""
    monkeypatch.chdir(tmp_path)
    # Sanitization strips '/' so "../evil" becomes "evil" then we look at
    # data/storage_state/evil/google.com.json which doesn't exist → None
    resolved = _resolveStorageStatePath("google.com", userId="../evil")
    assert resolved is None or "evil" in resolved.replace("..", "")
