"""Account routes for Neo4j-backed production auth."""

from __future__ import annotations

from django.urls import path

from apps.accounts import oauth_views

urlpatterns = [
    path("login/", oauth_views.login, name="account_login"),
    path("signup/", oauth_views.signup, name="account_signup"),
    path("logout/", oauth_views.logout, name="account_logout"),
    path("google/login/", oauth_views.googleLogin, name="google_login"),
    path("google/login/callback/", oauth_views.googleCallback, name="google_callback"),
    path("google/callback/", oauth_views.googleCallback, name="google_callback_alias"),
]
