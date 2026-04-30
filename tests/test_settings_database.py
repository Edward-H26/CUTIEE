from __future__ import annotations

from cutiee_site.settings import _databaseConfigFromUrl


def test_databaseConfigFromPostgresUrl() -> None:
    config = _databaseConfigFromUrl(
        "postgresql://cutiee:secret@example.com:5432/cutiee?sslmode=require"
    )

    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert config["NAME"] == "cutiee"
    assert config["USER"] == "cutiee"
    assert config["PASSWORD"] == "secret"
    assert config["HOST"] == "example.com"
    assert config["PORT"] == "5432"
    assert config["OPTIONS"] == {"sslmode": "require"}
