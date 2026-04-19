from django.contrib import admin
from django.urls import include, path

from apps.tasks.api import vlm_health, memory_export

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("memory/", include("apps.memory_app.urls")),
    path("memory/export/", memory_export, name = "memory_export"),
    path("audit/", include("apps.audit.urls")),
    path("api/vlm-health/", vlm_health, name = "vlm_health"),
    path("", include("apps.landing.urls")),
]
