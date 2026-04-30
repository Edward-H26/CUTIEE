"""Lightweight URL helpers shared across the harness, the memory
pipeline, and the Django task layer.

Keeping these out of `urllib.parse` avoids the extra import cost on the
hot screenshot path and lets the agent package stay free of Django
imports. The reflector, the runner factory, and the tasks services
layer all need to extract a hostname from a URL; keeping one
implementation prevents semantic drift (one version stripping the port,
another keeping it) that would surface as storage-state or domain-scoped
memory matches quietly failing.
"""

from __future__ import annotations

import re

_SCHEME_HOST_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)")


def hostFromUrl(url: str) -> str:
    """Return the hostname of `url` without scheme, port, path, or userinfo.

    Returns an empty string for URLs that do not carry a scheme. Strips
    the `:port` suffix so callers can safely feed the result to
    domain-string validators that reject colons (e.g. the RFC 1035
    regex the browser controller uses for storage-state path safety).
    """
    if not url:
        return ""
    match = _SCHEME_HOST_RE.match(url)
    if match is None:
        return ""
    host = match.group(1)
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    return host.split(":", 1)[0]
