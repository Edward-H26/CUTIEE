"""Prometheus exporter scaffolding for CUTIEE.

The exporter is off by default. Enable with `CUTIEE_ENABLE_PROMETHEUS=1`
in the environment AND install `prometheus-client` (not in the base
deps, kept optional so the local dev path stays small). Once enabled,
the `/metrics/` view at `cutiee_site/urls.py` returns Prometheus text
format with the metrics defined here.

Wiring strategy:

- `cu_cost_total` is incremented by `agent/harness/cost_ledger.py`
  whenever a non-zero `:CostLedger` increment lands. The label set
  is `(user_id, scope)` where scope is `per_task | per_hour | per_day`.
- `executions_active` is set as a gauge inside
  `apps/tasks/services.runTaskForUser`, which already tracks
  background thread lifecycle.
- `gemini_call_latency_seconds` is observed by
  `agent/routing/models/gemini_cu.py` around each Gemini API call.

Exporter call sites are guarded by `record_*` helper functions defined
here so the rest of the codebase never imports `prometheus_client`
directly. When the dep is missing the helpers are no-ops so the runtime
never raises.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("cutiee.metrics")

try:
    from prometheus_client import (  # type: ignore[import-untyped]
        CONTENT_TYPE_LATEST as _PROM_CONTENT_TYPE,
    )
    from prometheus_client import (  # type: ignore[import-untyped]
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest as _promGenerateLatest,
    )

    _registry = CollectorRegistry(auto_describe=True)

    _cuCostTotal = Counter(
        "cu_cost_total_usd",
        "Cumulative USD spent on Computer Use model calls.",
        labelnames=("scope",),
        registry=_registry,
    )
    _executionsActive = Gauge(
        "cu_executions_active",
        "Active CU runs currently executing.",
        registry=_registry,
    )
    _geminiLatency = Histogram(
        "cu_gemini_call_latency_seconds",
        "Latency of single Gemini Computer Use API calls.",
        buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32),
        registry=_registry,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:  # noqa: BLE001 - keep exporter optional
    PROMETHEUS_AVAILABLE = False
    _registry = None  # type: ignore[assignment]
    _PROM_CONTENT_TYPE = "text/plain; version=0.0.4"


def recordCost(scope: str, deltaUsd: float) -> None:
    if not PROMETHEUS_AVAILABLE or deltaUsd <= 0:
        return
    try:
        _cuCostTotal.labels(scope=scope).inc(deltaUsd)
    except Exception:  # noqa: BLE001 - metrics must never crash the run
        logger.debug("recordCost failed", exc_info=True)


def setActiveExecutions(count: int) -> None:
    if not PROMETHEUS_AVAILABLE:
        return
    try:
        _executionsActive.set(count)
    except Exception:  # noqa: BLE001
        logger.debug("setActiveExecutions failed", exc_info=True)


def observeGeminiLatency(seconds: float) -> None:
    if not PROMETHEUS_AVAILABLE or seconds < 0:
        return
    try:
        _geminiLatency.observe(seconds)
    except Exception:  # noqa: BLE001
        logger.debug("observeGeminiLatency failed", exc_info=True)


def renderTextFormat() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics/ HTTP response."""
    if not PROMETHEUS_AVAILABLE or _registry is None:
        return (b"# prometheus-client not installed\n", "text/plain; version=0.0.4")
    return _promGenerateLatest(_registry), _PROM_CONTENT_TYPE  # type: ignore[name-defined]
