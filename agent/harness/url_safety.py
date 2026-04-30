"""URL validation helpers for browser navigation boundaries."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})

PRIVATE_HOSTNAME_PREFIXES: frozenset[str] = frozenset(
    {
        "localhost",
        "ip6-localhost",
        "ip6-loopback",
    }
)


def addressIsPrivate(parsed: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
        or parsed.is_multicast
        or parsed.is_unspecified
    )


def hostnameIsPrivateOrUnresolved(hostname: str) -> bool:
    if not hostname:
        return True
    lowered = hostname.lower()
    if lowered in PRIVATE_HOSTNAME_PREFIXES:
        return True
    try:
        parsed = ipaddress.ip_address(lowered)
    except ValueError:
        try:
            addrInfos = socket.getaddrinfo(lowered, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return True
        if not addrInfos:
            return True
        for addrInfo in addrInfos:
            resolvedAddress = addrInfo[4][0]
            try:
                resolvedIp = ipaddress.ip_address(resolvedAddress)
            except ValueError:
                return True
            if addressIsPrivate(resolvedIp):
                return True
        return False
    return addressIsPrivate(parsed)


def sanitizeNavigationUrl(
    url: str,
    *,
    allowPrivateHosts: bool = False,
) -> tuple[str | None, str]:
    parsed = urlparse((url or "").strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        return None, "navigate requires a public http(s) URL"
    hostname = (parsed.hostname or "").lower()
    if not allowPrivateHosts and hostnameIsPrivateOrUnresolved(hostname):
        return None, "blocked private or unresolved navigation URL"
    return parsed.geturl(), ""
