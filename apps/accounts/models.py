from __future__ import annotations

from typing import Any, cast

from django.conf import settings
from django.db import models


class UserPreference(models.Model):
    """Framework-side per-user preferences that do not belong in Neo4j."""

    class Theme(models.TextChoices):
        AURORA = "aurora", "Aurora"
        SLATE = "slate", "Slate"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preference",
    )
    theme = models.CharField(max_length=24, choices=Theme.choices, default=Theme.AURORA)
    dashboard_window_days = models.PositiveSmallIntegerField(default=14)
    redact_audit_screenshots = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self) -> str:
        return f"UserPreference(user={self.user_id}, theme={self.theme})"

    @classmethod
    def for_user(cls, user: Any) -> "UserPreference":
        """Return the user's saved preferences or an unsaved default instance.

        The default instance carries the model field defaults (Aurora theme,
        14-day window, redaction on) without writing to the database. Callers
        can read attributes safely whether or not the user has ever opened
        `/me/preferences/`. Anonymous users get a fully default instance.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return cls()
        try:
            return cast("UserPreference", user.preference)
        except cls.DoesNotExist:
            return cls(user=user)
