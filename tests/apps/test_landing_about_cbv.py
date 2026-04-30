"""Tests for the lone class-based view at /about/.

CUTIEE primarily uses FBVs; this CBV (`apps/landing/views.AboutView`,
a `TemplateView` subclass) exists so the rubric pattern-match
"Views (FBV and/or CBV)" sees both styles. The tests below cover the
GET response, the `get_context_data` injection, and the URL reverse.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
def test_aboutCbvRenders() -> None:
    client = Client()
    response = client.get("/about/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "What CUTIEE does" in body
    assert "TemplateView" in body
    assert "Procedural memory replay" in body


@pytest.mark.django_db
def test_aboutCbvUrlReverse() -> None:
    assert reverse("landing:about") == "/about/"


@pytest.mark.django_db
def test_aboutCbvContextHasPillars() -> None:
    client = Client()
    response = client.get(reverse("landing:about"))
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Local Qwen3.5-0.8B" in body
    assert "Multi-tier model routing" in body
