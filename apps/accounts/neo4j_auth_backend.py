"""Django authentication backend backed by Neo4j `:User` nodes.

Adapted from miramemoria's backend, but CUTIEE does not keep a Django ORM
UserProfile mirror. Instead we return a lightweight `Neo4jUserProxy` object
that exposes the subset of Django's `User` interface that allauth, templates,
and session serialization need.
"""
from __future__ import annotations

from typing import Any

from django.contrib.auth.backends import BaseBackend

from agent.persistence import users as users_repo


class Neo4jUserProxy:
    """Duck-typed stand-in for `django.contrib.auth.models.User`."""

    def __init__(self, data: dict[str, Any]):
        self._data = data
        self.id = data["id"]
        self.pk = data["id"]
        self.username = data.get("username", "")
        self.email = data.get("email", "")
        self.is_active = bool(data.get("is_active", True))
        self.is_staff = bool(data.get("is_staff", False))
        self.is_superuser = bool(data.get("is_superuser", False))
        self.is_authenticated = True
        self.is_anonymous = False

    def __str__(self) -> str:
        return self.username or self.email or self.id

    def get_username(self) -> str:
        return self.username

    def has_perm(self, perm: str, obj: Any = None) -> bool:
        return self.is_staff

    def has_perms(self, perms: list[str], obj: Any = None) -> bool:
        return all(self.has_perm(p, obj) for p in perms)

    def has_module_perms(self, label: str) -> bool:
        return self.is_staff

    def get_session_auth_hash(self) -> str:
        return str(self._data.get("password_hash", ""))


class Neo4jAuthBackend(BaseBackend):

    def authenticate(
        self,
        request: Any,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> Neo4jUserProxy | None:
        identifier = username or kwargs.get("email") or kwargs.get("login")
        if not identifier or not password:
            return None
        user_data = users_repo.get_user_by_username(identifier) or users_repo.get_user_by_email(identifier)
        if user_data is None:
            return None
        if not users_repo.verify_password(user_data, password):
            return None
        users_repo.update_last_login(user_data["id"])
        return Neo4jUserProxy(user_data)

    def get_user(self, user_id: str) -> Neo4jUserProxy | None:
        data = users_repo.get_user_by_id(str(user_id))
        return Neo4jUserProxy(data) if data else None
