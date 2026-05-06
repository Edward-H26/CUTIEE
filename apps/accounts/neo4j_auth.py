"""Production auth objects and middleware backed by Neo4j sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest

from apps.accounts import repo

SESSION_USER_KEY = "neo4j_user_id"


@dataclass(frozen=True)
class Neo4jUser:
    id: str
    username: str = ""
    email: str = ""
    is_active: bool = True
    is_staff: bool = False
    is_superuser: bool = False

    @property
    def pk(self) -> str:
        return self.id

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_username(self) -> str:
        return self.username or self.email or self.id

    def __str__(self) -> str:
        return self.get_username()


class AnonymousNeo4jUser:
    id = ""
    pk = ""
    username = ""
    email = ""
    is_active = False
    is_staff = False
    is_superuser = False
    is_authenticated = False
    is_anonymous = True

    def get_username(self) -> str:
        return ""

    def __str__(self) -> str:
        return "AnonymousUser"


def userFromRecord(record: dict[str, Any]) -> Neo4jUser:
    return Neo4jUser(
        id=str(record.get("id") or ""),
        username=str(record.get("username") or record.get("name") or ""),
        email=str(record.get("email") or ""),
        is_active=bool(record.get("is_active", True)),
        is_staff=bool(record.get("is_staff", False)),
        is_superuser=bool(record.get("is_superuser", False)),
    )


def loginNeo4jUser(request: HttpRequest, user: Neo4jUser) -> None:
    request.session[SESSION_USER_KEY] = user.id
    request.user = user


def logoutNeo4jUser(request: HttpRequest) -> None:
    request.session.flush()
    request.user = AnonymousNeo4jUser()


class Neo4jAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        userId = request.session.get(SESSION_USER_KEY)
        request.user = AnonymousNeo4jUser()
        if userId:
            record = repo.getUser(str(userId))
            if record is not None:
                request.user = userFromRecord(record)
            else:
                request.session.pop(SESSION_USER_KEY, None)
        return self.get_response(request)
