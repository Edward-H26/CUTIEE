"""Django session engine backed by `:Session` nodes in Neo4j.

Adapted from miramemoria's SessionStore pattern.
"""

from __future__ import annotations

import logging

from django.contrib.sessions.backends.base import CreateError, SessionBase

from agent.persistence import sessions as sessions_repo

logger = logging.getLogger(__name__)


class SessionStore(SessionBase):
    def load(self) -> dict:
        record = sessions_repo.load_django_session(self.session_key)
        if record and record.get("data"):
            try:
                return self.decode(record["data"])
            except Exception:
                self._session_key = None
                return {}
        self._session_key = None
        return {}

    def exists(self, session_key: str) -> bool:
        return sessions_repo.django_session_exists(session_key)

    def create(self) -> None:
        for _ in range(10):
            self._session_key = self._get_new_session_key()
            try:
                self.save(must_create=True)
            except CreateError:
                continue
            self.modified = True
            return
        logger.error("Could not allocate unique session key after 10 retries")
        raise CreateError()

    def save(self, must_create: bool = False) -> None:
        if self.session_key is None:
            return self.create()
        if must_create and self.exists(self.session_key):
            raise CreateError()
        data = self.encode(self._get_session(no_load=must_create))
        expire = self.get_expiry_date().isoformat()
        sessions_repo.save_django_session(self.session_key, data, expire)

    def delete(self, session_key: str | None = None) -> None:
        key = session_key or self.session_key
        if key:
            sessions_repo.delete_django_session(key)

    @classmethod
    def clear_expired(cls) -> None:
        sessions_repo.cleanup_expired_sessions()
