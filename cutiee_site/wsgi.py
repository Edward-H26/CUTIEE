import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cutiee_site.settings")

application = get_wsgi_application()

from cutiee_site._internal_db import ensureInternalSchema  # noqa: E402

ensureInternalSchema()
