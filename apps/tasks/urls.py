from django.urls import path

from apps.tasks import api, views

app_name = "tasks"

urlpatterns = [
    path("", views.task_list, name = "list"),
    path("create/", views.create_task, name = "create"),
    path("dashboard/", views.cost_dashboard, name = "dashboard"),
    path("<str:task_id>/", views.task_detail, name = "detail"),
    path("<str:task_id>/run/", api.run_task_view, name = "run"),
    path("<str:task_id>/delete/", api.delete_task, name = "delete"),
    path("<str:task_id>/json/", api.task_detail_json, name = "detail_json"),
    path("api/status/<str:execution_id>/", api.task_status, name = "status"),
    path(
        "api/screenshot/<str:execution_id>/<int:step_index>.png",
        api.step_screenshot,
        name = "step_screenshot",
    ),
    path(
        "api/approval/<str:execution_id>/",
        api.approval_pending,
        name = "approval_pending",
    ),
    path(
        "api/approval/<str:execution_id>/<str:decision>/",
        api.approval_decide,
        name = "approval_decide",
    ),
    path(
        "api/preview/<str:execution_id>/",
        api.preview_pending,
        name = "preview_pending",
    ),
    path(
        "api/preview/<str:execution_id>/<str:decision>/",
        api.preview_decide,
        name = "preview_decide",
    ),
    path("api/cost-summary/", api.cost_summary, name = "cost_summary"),
    path("api/cost-timeseries/", api.cost_timeseries, name = "cost_timeseries"),
    path("api/tier-distribution/", api.tier_distribution, name = "tier_distribution"),
    path("api/memory-stats/", api.memory_stats, name = "memory_stats"),
    path("api/audit/", api.audit_feed, name = "audit_feed"),
]
