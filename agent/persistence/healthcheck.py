"""Neo4j connection health check + diagnostic helpers.

Surfaces clear, actionable error messages instead of letting raw
`neo4j.exceptions.ClientError` / `ServiceUnavailable` bubble up to a
500 page. Used by Django views that touch the database to render a
friendly "Neo4j unreachable" UI instead of crashing.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("cutiee.neo4j_health")


@dataclass
class HealthResult:
    reachable: bool
    bolt_url: str
    error: str = ""
    remediation: str = ""

    @property
    def short_summary(self) -> str:
        if self.reachable:
            return f"Neo4j OK at {self.bolt_url}"
        return f"Neo4j unreachable at {self.bolt_url}: {self.error}"


def checkNeo4jReachable(timeoutSec: float = 2.0) -> HealthResult:
    """Fast probe: open a session, run `RETURN 1`, close. ~200ms when healthy.

    Catches every neo4j exception type and translates to a remediation
    hint the operator can act on. Never raises — always returns a
    HealthResult.
    """
    boltUrl = (
        os.environ.get("NEO4J_BOLT_URL")
        or os.environ.get("NEO4J_URI")
        or "(unset)"
    )

    if boltUrl == "(unset)":
        return HealthResult(
            reachable = False,
            bolt_url = boltUrl,
            error = "NEO4J_BOLT_URL not set",
            remediation = "Set NEO4J_BOLT_URL in .env. For local dev: bolt://localhost:7687. For Aura: neo4j+s://<id>.databases.neo4j.io",
        )

    try:
        from neo4j import GraphDatabase
        from neo4j.exceptions import (
            AuthError,
            ClientError,
            ConfigurationError,
            ServiceUnavailable,
        )
    except ImportError:
        return HealthResult(
            reachable = False,
            bolt_url = boltUrl,
            error = "neo4j Python driver not installed",
            remediation = "Run `uv sync` to install dependencies",
        )

    user = os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")

    try:
        driver = GraphDatabase.driver(
            boltUrl,
            auth = (user, password) if user else None,
            connection_timeout = timeoutSec,
        )
        try:
            with driver.session() as session:
                result = session.run("RETURN 1 AS ok")
                value = result.single()
                if value and value["ok"] == 1:
                    return HealthResult(reachable = True, bolt_url = boltUrl)
                return HealthResult(
                    reachable = False, bolt_url = boltUrl,
                    error = "session.run returned unexpected shape",
                    remediation = "Check Neo4j server logs",
                )
        finally:
            driver.close()
    except ServiceUnavailable as exc:
        return HealthResult(
            reachable = False, bolt_url = boltUrl, error = str(exc)[:200],
            remediation = (
                "Neo4j server isn't accepting connections. "
                "For local dev: `./scripts/neo4j_up.sh` to start the docker container. "
                "For Aura: verify the instance is running at https://console.neo4j.io"
            ),
        )
    except AuthError as exc:
        return HealthResult(
            reachable = False, bolt_url = boltUrl, error = "auth failed (wrong username/password)",
            remediation = (
                "NEO4J_USERNAME/NEO4J_PASSWORD don't match what the server expects. "
                "Check your .env values. If you've hit the rate limit, wait 10s and retry. "
                f"Detail: {str(exc)[:120]}"
            ),
        )
    except (ConfigurationError, ClientError) as exc:
        msg = str(exc)
        remediation = "Check NEO4J_BOLT_URL format and Neo4j server config"
        if "rate" in msg.lower() or "RateLimit" in msg:
            remediation = (
                "Auth rate limit hit. Wait 10s and retry. "
                "Likely cause: too many wrong-password attempts in succession."
            )
        return HealthResult(
            reachable = False, bolt_url = boltUrl, error = msg[:200],
            remediation = remediation,
        )
    except Exception as exc:  # noqa: BLE001 - catch-all so we never raise
        return HealthResult(
            reachable = False, bolt_url = boltUrl, error = repr(exc)[:200],
            remediation = "Unexpected error — check the server log for the full stack",
        )


def logHealthOnStartup() -> None:
    """Best-effort startup log so operators see Neo4j status immediately."""
    result = checkNeo4jReachable()
    if result.reachable:
        logger.info("Neo4j health: %s", result.short_summary)
    else:
        logger.warning(
            "Neo4j health: %s\n  Remediation: %s",
            result.short_summary, result.remediation,
        )
