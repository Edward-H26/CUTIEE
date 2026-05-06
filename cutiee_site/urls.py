from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path

from agent.persistence.metrics import renderTextFormat
from apps.tasks.api import vlm_health, memory_export


def _liveness(_request) -> HttpResponse:
    """Cheap 200 response for Render's healthCheckPath.

    Liveness only signals that the Django process is up and serving
    requests. Deeper probes (Neo4j, Gemini) go through /api/vlm-health/
    and the per-page fallback UIs so that a transient database outage
    does not restart every web dyno.
    """
    return HttpResponse("ok", content_type="text/plain")


def _metrics(_request) -> HttpResponse:
    """Prometheus text-format metrics endpoint, gated on CUTIEE_ENABLE_PROMETHEUS.

    The exporter ships off by default. When the operator sets
    `CUTIEE_ENABLE_PROMETHEUS=1` AND installs `prometheus-client`,
    `agent/persistence/metrics.py` registers cost / execution / latency
    metrics and this view serves them. Otherwise the response is a
    short comment line so a misconfigured scrape job does not 500.
    """
    body, contentType = renderTextFormat()
    return HttpResponse(body, content_type=contentType)


urlpatterns = [
    path("me/", include("apps.accounts.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("memory/", include("apps.memory_app.urls")),
    path("memory/export/", memory_export, name="memory_export"),
    path("audit/", include("apps.audit.urls")),
    path("api/vlm-health/", vlm_health, name="vlm_health"),
    path("health/", _liveness, name="liveness"),
    path("", include("apps.landing.urls")),
]

if getattr(settings, "CUTIEE_NEO4J_FRAMEWORK_AUTH", False):
    urlpatterns.insert(0, path("accounts/", include("apps.accounts.neo4j_urls")))
else:
    from django.contrib import admin

    urlpatterns.insert(0, path("accounts/", include("allauth.urls")))
    urlpatterns.insert(0, path("admin/", admin.site.urls))

if getattr(settings, "CUTIEE_ENABLE_PROMETHEUS", False):
    urlpatterns.append(path("metrics/", _metrics, name="metrics"))
