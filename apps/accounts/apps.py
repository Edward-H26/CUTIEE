from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self) -> None:
        from django.conf import settings

        if getattr(settings, "CUTIEE_NEO4J_FRAMEWORK_AUTH", False):
            return

        from apps.accounts import signals  # noqa: F401
        from cutiee_site._internal_db import ensureInternalSchema

        ensureInternalSchema()
