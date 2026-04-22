"""Django AppConfig for the tasks app.

The `ready()` hook auto-runs the Neo4j bootstrap once per process so a
fresh deploy to a new AuraDB instance never hits a missing-constraint
error at first task. Every Cypher statement in the bootstrap is
idempotent, so running it repeatedly is safe; the module-level
`_BOOTSTRAPPED` flag keeps the cost to one round-trip per Python
process even when Django re-imports. Bootstrap failures (Neo4j
unreachable, AuraDB paused) log and continue so a transient outage
never blocks worker startup.
"""
from __future__ import annotations

import logging
import os

from django.apps import AppConfig

logger = logging.getLogger("cutiee.bootstrap")

_BOOTSTRAPPED = False


class TasksConfig(AppConfig):
    name = "apps.tasks"
    label = "tasks"

    def ready(self) -> None:
        global _BOOTSTRAPPED
        if _BOOTSTRAPPED:
            return
        _BOOTSTRAPPED = True
        if os.environ.get("CUTIEE_SKIP_AUTO_BOOTSTRAP", "").strip().lower() in {"1", "true", "yes"}:
            logger.debug("auto-bootstrap skipped via CUTIEE_SKIP_AUTO_BOOTSTRAP")
            return
        # Skip during pytest and management commands that have no need
        # to hit the graph (collectstatic, check, shell without run).
        # `runserver`, `gunicorn`, and `uvicorn` all set no such flag,
        # so they do run the bootstrap.
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        try:
            from agent.persistence.bootstrap import bootstrap
            bootstrap()
        except Exception as exc:  # noqa: BLE001 - never block worker boot on bootstrap failure
            logger.warning(
                "Automatic Neo4j bootstrap failed: %r. Run "
                "`python -m agent.persistence.bootstrap` manually once the "
                "database is reachable.",
                exc,
            )
