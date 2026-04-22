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
