"""One-shot bootstrap for Django's in-process framework SQLite.

When `DJANGO_INTERNAL_DB_URL` is unset (or points at the shared-cache
in-memory URI), the schema lives only inside the running process. Two
concerns to handle:

1. Schema creation: run `migrate` once during process startup so
   subsequent connections find the framework tables (auth, contenttypes,
   sites, allauth, sessions).
2. Lifetime: SQLite frees an in-memory database the moment the *last*
   connection to it closes. Django opens and closes connections per
   request, so without a keep-alive the schema would disappear between
   the bootstrap and the first request. The helper holds one anonymous
   connection open for the entire process lifetime.

The helper is idempotent and is safe to call multiple times: a process
flag short-circuits after the first invocation.
"""
from __future__ import annotations

import sqlite3
import sys
import threading

_LOCK = threading.Lock()
_BOOTSTRAPPED = False
_KEEPALIVE: sqlite3.Connection | None = None


def ensureInternalSchema() -> None:
    """Run framework migrations against the in-process SQLite once."""
    global _BOOTSTRAPPED, _KEEPALIVE
    if _BOOTSTRAPPED:
        return
    with _LOCK:
        if _BOOTSTRAPPED:
            return
        from django.conf import settings
        defaultDb = settings.DATABASES.get("default", {})
        name = defaultDb.get("NAME", "")
        engine = defaultDb.get("ENGINE", "")
        isMemory = engine == "django.db.backends.sqlite3" and (
            ":memory:" in str(name) or "mode=memory" in str(name)
        )
        if not isMemory:
            _BOOTSTRAPPED = True
            return

        # Pin one connection open so the in-memory database survives the
        # gap between migrate finishing and the first request opening
        # its own connection.
        useUri = bool(defaultDb.get("OPTIONS", {}).get("uri"))
        _KEEPALIVE = sqlite3.connect(str(name), uri = useUri, check_same_thread = False)

        sys.stderr.write("[cutiee] bootstrapping in-memory framework SQLite...\n")
        sys.stderr.flush()
        from django.core.management import call_command
        call_command("migrate", "--no-input", verbosity = 0)
        sys.stderr.write("[cutiee] in-memory framework SQLite ready.\n")
        sys.stderr.flush()
        _BOOTSTRAPPED = True
