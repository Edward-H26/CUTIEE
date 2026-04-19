"""Semantic credential namespace.

Credentials are persisted as `:MemoryBullet` nodes with `is_credential=True`,
`memory_type='semantic'`, and `tags` containing `credential:<domain>`. The
content is encrypted at rest with `cryptography.fernet`. The retrieval path
in `ACEMemory` already filters bullets where `is_credential=True`, so they
never enter a prompt block. They are only surfaced via the explicit
`getCredential(domain)` accessor used by the replay executor's variable
resolver.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .ace_memory import ACEMemory
from .bullet import Bullet


def _resolveFernet() -> Any:
    from cryptography.fernet import Fernet

    raw = os.environ.get("CUTIEE_CREDENTIAL_KEY")
    if not raw:
        raise RuntimeError(
            "CUTIEE_CREDENTIAL_KEY not set. Generate one via "
            "`uv run python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'`."
        )
    return Fernet(raw.encode("utf-8"))


@dataclass
class SemanticCredentialStore:
    memory: ACEMemory

    def putCredential(self, domain: str, secret: str, *, label: str = "") -> Bullet:
        cipher = _resolveFernet()
        encrypted = cipher.encrypt(secret.encode("utf-8")).decode("utf-8")
        bullet = Bullet(
            content = encrypted,
            memory_type = "semantic",
            tags = [f"credential:{domain}", "credential"],
            topic = f"credential:{domain}",
            concept = label or "credential",
            is_credential = True,
        )
        self.memory.store.upsertBullet(self.memory.userId, bullet)
        self.memory.bullets[bullet.id] = bullet
        return bullet

    def getCredential(self, domain: str) -> str | None:
        cipher = _resolveFernet()
        for bullet in self.memory.bullets.values():
            if not bullet.is_credential:
                continue
            if any(tag == f"credential:{domain}" for tag in bullet.tags):
                return cipher.decrypt(bullet.content.encode("utf-8")).decode("utf-8")
        return None

    def listDomains(self) -> list[str]:
        domains: list[str] = []
        for bullet in self.memory.bullets.values():
            if not bullet.is_credential:
                continue
            for tag in bullet.tags:
                if tag.startswith("credential:"):
                    domains.append(tag.split(":", 1)[1])
        return sorted(set(domains))
