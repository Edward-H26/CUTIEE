from __future__ import annotations

from django.contrib import admin

from apps.accounts.models import UserPreference


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    """Read-mostly view of per-user framework preferences in /admin/.

    The preference row is created lazily by the preferences view, so the
    admin list is also a quick way to see which users have ever opened
    /me/preferences/ versus the implicit default-instance population.
    """

    list_display = (
        "user",
        "theme",
        "dashboard_window_days",
        "redact_audit_screenshots",
        "updated_at",
    )
    list_filter = ("theme", "redact_audit_screenshots")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("user_id",)
