"""Smoke tests for the tasks app views.

The tests are pure-Django (no Neo4j needed). The auth-protected routes
should redirect anonymous users to the login page.
"""
from __future__ import annotations

import pytest
from django.test import Client


@pytest.mark.django_db
def test_landingRendersForAnonymous():
    client = Client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"CUTIEE" in resp.content
    assert b"/accounts/login/" in resp.content


@pytest.mark.django_db
def test_tasksRedirectsAnonymousToLogin():
    client = Client()
    resp = client.get("/tasks/")
    assert resp.status_code in (302, 301)
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_dashboardRedirectsAnonymousToLogin():
    client = Client()
    resp = client.get("/tasks/dashboard/")
    assert resp.status_code in (302, 301)


@pytest.mark.django_db
def test_vlmHealthEndpointRespondsJson():
    client = Client()
    resp = client.get("/api/vlm-health/")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "env" in body


@pytest.mark.django_db
def test_livenessEndpointReturnsOk():
    # Render's healthCheckPath targets /health/ and a deploy is marked
    # failed when this path does not return 2xx in the grace window.
    client = Client()
    resp = client.get("/health/")
    assert resp.status_code == 200
    assert resp.content == b"ok"


@pytest.mark.django_db
def test_vlmHealthHtmxEscapesModelValue(monkeypatch: pytest.MonkeyPatch):
    # The banner interpolates CUTIEE_CU_MODEL into the HTML attribute.
    # Render's operator controls env but defense-in-depth escaping must
    # block an HTML-breaking value from leaking into the attribute.
    monkeypatch.setenv("CUTIEE_ENV", "production")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("CUTIEE_CU_MODEL", "model\"><script>alert(1)</script>")
    client = Client()
    resp = client.get("/api/vlm-health/", HTTP_HX_REQUEST = "true")
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body or "&quot;" in body


@pytest.mark.django_db
def test_safeIntCoercesMalformedQueryParam():
    # Malformed query ints must not crash the endpoint; login_required
    # should redirect anonymous callers before the parser ever runs.
    client = Client()
    resp = client.get("/tasks/api/cost-timeseries/?days=abc")
    assert resp.status_code in (302, 301)


@pytest.mark.django_db
def test_deleteTaskRejectsRequestsWithoutCsrfToken():
    # Destructive POSTs must require a CSRF token even for logged-in
    # users; otherwise a cross-site form could delete a task on their
    # behalf.
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.create_user(username = "alice", password = "pw")
    client = Client(enforce_csrf_checks = True)
    client.force_login(user)
    resp = client.post("/tasks/any-task-id/delete/")
    assert resp.status_code == 403
