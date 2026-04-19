import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cutiee_site.settings")

application = get_asgi_application()

from cutiee_site._internal_db import ensureInternalSchema  # noqa: E402

ensureInternalSchema()
