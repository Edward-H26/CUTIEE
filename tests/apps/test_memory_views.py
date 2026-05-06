"""Tests for the memory dashboard UI."""

from __future__ import annotations

import pytest
from django.test import Client
from django.utils.html import escape

from apps.memory_app.repo import MemoryBulletRow


@pytest.mark.django_db
def test_memoryDashboardShowsHumanBulletAndMachineDetails(monkeypatch: pytest.MonkeyPatch) -> None:
    from django.contrib.auth import get_user_model
    from apps.memory_app import views as memoryViews

    user = get_user_model().objects.create_user(username="memory-user", password="pw")
    client = Client()
    client.force_login(user)
    machineContent = "step_index=1 action=click_at target='' value='' coordinate=(640,320)"
    bullet = MemoryBulletRow(
        {
            "id": "bullet-1",
            "content": machineContent,
            "human_content": "Step 2: click (640, 320)",
            "memory_type": "procedural",
            "tags": [],
            "helpful_count": 1,
            "harmful_count": 0,
            "semantic_strength": 0.0,
            "episodic_strength": 0.0,
            "procedural_strength": 1.0,
            "topic": "",
            "concept": "",
            "is_seed": False,
        }
    )

    monkeypatch.setattr(memoryViews, "listBulletsForUser", lambda _userId: [bullet])
    monkeypatch.setattr(memoryViews, "listTemplatesForUser", lambda _userId: [])
    monkeypatch.setattr(
        memoryViews,
        "memoryDashboardStats",
        lambda _userId: {
            "bullet_count": 1,
            "template_count": 0,
            "total_helpful": 1,
            "total_harmful": 0,
        },
    )

    resp = client.get("/memory/")

    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    assert "Step 2: click (640, 320)" in body
    assert "Machine format" in body
    assert escape(machineContent) in body
