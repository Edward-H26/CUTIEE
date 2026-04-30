from django.urls import path

from apps.memory_app import views

app_name = "memory_app"

urlpatterns = [
    path("", views.bullet_list, name="list"),
    path("templates/<str:template_id>/stale/", views.mark_stale, name="mark_stale"),
]
