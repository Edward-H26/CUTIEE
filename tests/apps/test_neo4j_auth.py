from __future__ import annotations

from django.test import RequestFactory

from apps.accounts import oauth_views
from apps.accounts.neo4j_auth import (
    SESSION_USER_KEY,
    AnonymousNeo4jUser,
    Neo4jUser,
    loginNeo4jUser,
    logoutNeo4jUser,
    userFromRecord,
)


class _Session(dict):
    def __init__(self) -> None:
        super().__init__()
        self.wasFlushed = False

    def flush(self) -> None:
        self.clear()
        self.wasFlushed = True


def test_userFromRecordBuildsAuthenticatedNeo4jUser() -> None:
    user = userFromRecord(
        {
            "id": "google:123",
            "username": "Ada",
            "email": "ada@example.com",
            "is_staff": True,
        }
    )

    assert user.pk == "google:123"
    assert user.get_username() == "Ada"
    assert user.email == "ada@example.com"
    assert user.is_authenticated is True
    assert user.is_staff is True


def test_loginAndLogoutUseNeo4jSessionKey() -> None:
    request = RequestFactory().get("/tasks/")
    request.session = _Session()
    user = Neo4jUser(id="google:123", username="Ada", email="ada@example.com")

    loginNeo4jUser(request, user)

    assert request.session[SESSION_USER_KEY] == "google:123"
    assert request.user == user

    logoutNeo4jUser(request)

    assert request.session.wasFlushed is True
    assert isinstance(request.user, AnonymousNeo4jUser)


def test_neo4jLoginPagePreservesNextParameter() -> None:
    request = RequestFactory().get("/accounts/login/?next=/me/preferences/")
    request.user = AnonymousNeo4jUser()

    response = oauth_views.login(request)

    assert response.status_code == 200
    assert b"?next=/me/preferences/" in response.content
