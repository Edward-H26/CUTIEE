"""Mirror every Django ORM User into Neo4j as a `:User` node.

This keeps Django's native auth flow intact (allauth, admin, sessions) while
ensuring all domain queries can scope to a Neo4j user via `u.id = <django_pk>`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from agent.persistence.neo4j_client import run_query


@receiver(post_save, sender = settings.AUTH_USER_MODEL)
def sync_user_to_neo4j(sender, instance, created, **kwargs) -> None:
    run_query(
        """
        MERGE (u:User {id: $id})
        SET u.username = $username,
            u.email = $email,
            u.is_active = $is_active,
            u.is_staff = $is_staff,
            u.updated_at = $updated_at
        """,
        id = str(instance.pk),
        username = instance.get_username(),
        email = getattr(instance, "email", "") or "",
        is_active = bool(instance.is_active),
        is_staff = bool(instance.is_staff),
        updated_at = datetime.now(timezone.utc).isoformat(),
    )
