"""Neo4j persistence layer for CUTIEE.

Ported from miramemoria.app.services.neo4j_memory with CUTIEE-specific env vars
and a no-silent-fallback policy: missing config raises RuntimeError immediately.
"""
from . import sessions
from .neo4j_client import (
    close_driver,
    get_driver,
    run_query,
    run_single,
)

__all__ = [
    "close_driver",
    "get_driver",
    "run_query",
    "run_single",
    "sessions",
]
