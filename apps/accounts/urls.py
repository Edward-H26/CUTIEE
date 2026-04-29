"""URL routes for the accounts app's UserPreference UI.

Mounted at `/me/` from the project urlconf so it never collides with
allauth's `/accounts/` namespace.
"""
from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("preferences/", views.preferences, name = "preferences"),
]
