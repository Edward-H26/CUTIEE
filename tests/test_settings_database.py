from __future__ import annotations

import pytest

from cutiee_site import settings as settingsMod
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


def test_productionDatabaseConfigAllowsNeo4jFrameworkAuthWithoutSqlUrl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DJANGO_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(settingsMod, "CUTIEE_NEO4J_FRAMEWORK_AUTH", True)
    monkeypatch.setattr(settingsMod, "IS_PYTEST", False)

    config = settingsMod._productionDatabaseConfig()

    assert config["ENGINE"] == "django.db.backends.sqlite3"
    assert config["OPTIONS"]["uri"] is True


def test_productionDatabaseConfigIgnoresSqlUrlForNeo4jFrameworkAuth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DJANGO_DATABASE_URL", "postgresql://cutiee:secret@example.com/cutiee")
    monkeypatch.setattr(settingsMod, "CUTIEE_NEO4J_FRAMEWORK_AUTH", True)
    monkeypatch.setattr(settingsMod, "IS_PYTEST", False)

    config = settingsMod._productionDatabaseConfig()

    assert config["ENGINE"] == "django.db.backends.sqlite3"
    assert config["NAME"] == "file:cutiee_internals?mode=memory&cache=shared"


def test_productionDatabaseConfigRequiresSqlOnlyForLegacyFrameworkAuth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DJANGO_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(settingsMod, "CUTIEE_NEO4J_FRAMEWORK_AUTH", False)
    monkeypatch.setattr(settingsMod, "IS_PYTEST", False)

    with pytest.raises(RuntimeError, match="CUTIEE_NEO4J_FRAMEWORK_AUTH=false"):
        settingsMod._productionDatabaseConfig()
