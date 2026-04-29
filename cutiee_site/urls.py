from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path

from apps.tasks.api import vlm_health, memory_export


def _liveness(_request) -> HttpResponse:
    """Cheap 200 response for Render's healthCheckPath.

    Liveness only signals that the Django process is up and serving
    requests. Deeper probes (Neo4j, Gemini) go through /api/vlm-health/
    and the per-page fallback UIs so that a transient database outage
    does not restart every web dyno.
    """
    return HttpResponse("ok", content_type = "text/plain")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("me/", include("apps.accounts.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("memory/", include("apps.memory_app.urls")),
    path("memory/export/", memory_export, name = "memory_export"),
    path("audit/", include("apps.audit.urls")),
    path("api/vlm-health/", vlm_health, name = "vlm_health"),
    path("health/", _liveness, name = "liveness"),
    path("", include("apps.landing.urls")),
]
