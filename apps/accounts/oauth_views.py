"""Neo4j-backed Google OAuth views for production."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from apps.accounts import repo
from apps.accounts.neo4j_auth import loginNeo4jUser, logoutNeo4jUser, userFromRecord

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_STATE_KEY = "google_oauth_state"
_NEXT_KEY = "google_oauth_next"


def login(request: HttpRequest) -> HttpResponse:
    if getattr(request.user, "is_authenticated", False):
        return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
    return render(
        request,
        "account/neo4j_login.html",
        {"nextUrl": request.GET.get("next", "")},
    )


def signup(request: HttpRequest) -> HttpResponse:
    return HttpResponseRedirect(reverse("account_login"))


def googleLogin(request: HttpRequest) -> HttpResponse:
    state = secrets.token_urlsafe(32)
    request.session[_STATE_KEY] = state
    request.session[_NEXT_KEY] = request.GET.get("next") or settings.LOGIN_REDIRECT_URL
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": request.build_absolute_uri(reverse("google_callback")),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return HttpResponseRedirect(f"{_GOOGLE_AUTH_URL}?{urlencode(params)}")


def googleCallback(request: HttpRequest) -> HttpResponse:
    state = request.GET.get("state", "")
    expectedState = request.session.pop(_STATE_KEY, "")
    if not state or state != expectedState:
        return HttpResponseBadRequest("Invalid OAuth state.")
    code = request.GET.get("code", "")
    if not code:
        return HttpResponseBadRequest("Missing OAuth code.")

    redirectUri = request.build_absolute_uri(reverse("google_callback"))
    tokenResponse = httpx.post(
        _GOOGLE_TOKEN_URL,
        data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirectUri,
        },
        timeout=10.0,
    )
    tokenResponse.raise_for_status()
    accessToken = tokenResponse.json().get("access_token", "")
    if not accessToken:
        return HttpResponseBadRequest("Google did not return an access token.")

    userInfoResponse = httpx.get(
        _GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {accessToken}"},
        timeout=10.0,
    )
    userInfoResponse.raise_for_status()
    userInfo = userInfoResponse.json()
    record = repo.upsertGoogleUser(
        googleSub=str(userInfo.get("sub") or ""),
        email=str(userInfo.get("email") or ""),
        name=str(userInfo.get("name") or ""),
        picture=str(userInfo.get("picture") or ""),
    )
    loginNeo4jUser(request, userFromRecord(record))
    nextUrl = _safeNextUrl(request, request.session.pop(_NEXT_KEY, settings.LOGIN_REDIRECT_URL))
    return HttpResponseRedirect(nextUrl or settings.LOGIN_REDIRECT_URL)


@require_http_methods(["GET", "POST"])
def logout(request: HttpRequest) -> HttpResponse:
    logoutNeo4jUser(request)
    return HttpResponseRedirect("/")


def _safeNextUrl(request: HttpRequest, nextUrl: str) -> str:
    if url_has_allowed_host_and_scheme(
        nextUrl,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return nextUrl
    return settings.LOGIN_REDIRECT_URL
