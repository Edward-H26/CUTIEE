"""CSV-export endpoint test for the cost-timeseries dashboard download.

Verifies that `GET /tasks/api/cost-timeseries.csv` returns a CSV with the
expected header row, the right Content-Type, and the attachment-style
Content-Disposition. The endpoint catches Neo4j failures and falls back
to an empty series, so the test stays independent of a live Neo4j.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.mark.django_db
def test_costTimeseriesCsvHeadersAndShape() -> None:
    user = get_user_model().objects.create_user(username="csv-export", password="pw")
    client = Client()
    client.force_login(user)

    sample = [
        {"day": "2026-04-28", "daily_cost": 0.0042},
        {"day": "2026-04-29", "daily_cost": 0.0117},
    ]
    with mock.patch(
        "apps.tasks.repo.costTimeseriesForUser",
        return_value=sample,
    ):
        response = client.get("/tasks/api/cost-timeseries.csv?days=14")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    assert ".csv" in response["Content-Disposition"]

    body = response.content.decode("utf-8")
    rows = [line for line in body.splitlines() if line]
    assert rows[0] == "day,daily_cost_usd"
    assert "2026-04-28,0.0042" in body
    assert "2026-04-29,0.0117" in body


@pytest.mark.django_db
def test_costTimeseriesCsvEmptyOnDbError() -> None:
    user = get_user_model().objects.create_user(username="csv-empty", password="pw")
    client = Client()
    client.force_login(user)

    with mock.patch(
        "apps.tasks.repo.costTimeseriesForUser",
        side_effect=RuntimeError("neo4j down"),
    ):
        response = client.get("/tasks/api/cost-timeseries.csv")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    body = response.content.decode("utf-8").strip().splitlines()
    assert body == ["day,daily_cost_usd"]
