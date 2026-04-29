from django.urls import path

from apps.landing import views

app_name = "landing"

urlpatterns = [
    path("", views.index, name = "index"),
    path("about/", views.AboutView.as_view(), name = "about"),
]
