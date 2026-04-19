"""Django settings for CUTIEE.

All domain data lives in Neo4j. Django's framework-only bookkeeping
(contenttypes, admin, sites, allauth) runs against an ephemeral
in-memory SQLite that never touches disk. The Django ORM holds zero
application state — every domain entity (User, Task, Bullet, Audit,
Procedure) is persisted via Cypher in `apps/*/repo.py`.
"""
from __future__ import annotations

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(str(BASE_DIR / ".env"))

CUTIEE_ENV = env("CUTIEE_ENV", default = None)
if CUTIEE_ENV not in {"local", "production"}:
    raise RuntimeError(
        "CUTIEE_ENV must be set to 'local' or 'production'. See .env.example."
    )

for required_key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    if not env(required_key, default = ""):
        raise RuntimeError(
            f"{required_key} is required. Google OAuth is the primary auth flow. "
            "Create credentials at https://console.cloud.google.com/apis/credentials."
        )

if CUTIEE_ENV == "production" and not env("GEMINI_API_KEY", default = ""):
    raise RuntimeError("GEMINI_API_KEY required when CUTIEE_ENV=production.")
# CUTIEE_ENV=local uses MockComputerUseClient (post-pivot — no Qwen
# server required). Local mode just needs Neo4j; the model client is
# the scripted demo stand-in.

if not env("NEO4J_BOLT_URL", default = "") and env("NEO4J_URI", default = ""):
    # Back-compat: miramemoria-style .env files use NEO4J_URI.
    os.environ["NEO4J_BOLT_URL"] = env("NEO4J_URI")

for required_key in ("NEO4J_BOLT_URL", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
    if not env(required_key, default = ""):
        raise RuntimeError(
            f"{required_key} is required. Neo4j is the default database. "
            "Start it locally via `./scripts/neo4j_up.sh`, or set AuraDB "
            "credentials for production. NEO4J_URI is also accepted."
        )

SECRET_KEY = env("DJANGO_SECRET_KEY", default = "cutiee-insecure-dev-only-change-me")
if CUTIEE_ENV == "production" and SECRET_KEY.startswith("cutiee-insecure"):
    raise RuntimeError(
        "DJANGO_SECRET_KEY must be set to a long random value when CUTIEE_ENV=production. "
        "Render's `generateValue: true` produces a suitable secret automatically."
    )

DEBUG = env.bool("DJANGO_DEBUG", default = CUTIEE_ENV == "local")
# Defaults are scoped to the localhost dev box. Production deployments must
# enumerate their own host(s) via DJANGO_ALLOWED_HOSTS / DJANGO_CSRF_TRUSTED_ORIGINS
# (set in render.yaml). This avoids trusting every *.onrender.com tenant by
# default, which would let any sibling subdomain pass the CSRF origin check.
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default = ["localhost", "127.0.0.1"],
)
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default = [],
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "rest_framework",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "apps.accounts",
    "apps.tasks",
    "apps.memory_app",
    "apps.audit",
    "apps.landing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "cutiee_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "cutiee_site.wsgi.application"
ASGI_APPLICATION = "cutiee_site.asgi.application"

# Shared-cache in-memory SQLite. Lives only inside the running Python
# process; all Django connections in that process see the same tables.
# Worker boundaries reset state, which is intentional: the only data
# stored here is Django's framework bookkeeping (contenttypes,
# auth_permission seed rows, allauth config). Application data lives
# exclusively in Neo4j via apps/*/repo.py Cypher queries.
#
# Hard-coded by design: this is a Neo4j-only framework. There is no env
# escape hatch to a disk-backed SQLite, and `DJANGO_INTERNAL_DB_URL` is
# intentionally ignored.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "file:cutiee_internals?mode=memory&cache=shared",
        "OPTIONS": {"uri": True, "transaction_mode": "IMMEDIATE"},
    },
}

NEO4J_BOLT_URL = env("NEO4J_BOLT_URL")
NEO4J_USERNAME = env("NEO4J_USERNAME")
NEO4J_PASSWORD = env("NEO4J_PASSWORD")
NEO4J_DATABASE = env("NEO4J_DATABASE", default = "neo4j")

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

SESSION_COOKIE_AGE = 60 * 60 * 24 * 14

SITE_ID = 1
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/tasks/"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = env("ACCOUNT_EMAIL_VERIFICATION", default = "optional")
ACCOUNT_EMAIL_NOTIFICATIONS = env.bool("ACCOUNT_EMAIL_NOTIFICATIONS", default = False)

# Email backend defaults to the console in dev so signup never blocks on
# an SMTP connection. Production sets DJANGO_EMAIL_BACKEND explicitly.
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default = "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", default = "no-reply@cutiee.local")

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": env("GOOGLE_CLIENT_ID"),
            "secret": env("GOOGLE_CLIENT_SECRET"),
            "key": "",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    },
}
SOCIALACCOUNT_LOGIN_ON_GET = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

CUTIEE_RECENCY_WINDOW = env.int("CUTIEE_RECENCY_WINDOW", default = 3)
CUTIEE_TEMPLATE_MATCH_THRESHOLD = env.float("CUTIEE_TEMPLATE_MATCH_THRESHOLD", default = 0.85)
CUTIEE_CONFIDENCE_THRESHOLDS = {
    1: env.float("CUTIEE_CONFIDENCE_THRESHOLD_TIER1", default = 0.75),
    2: env.float("CUTIEE_CONFIDENCE_THRESHOLD_TIER2", default = 0.65),
    3: env.float("CUTIEE_CONFIDENCE_THRESHOLD_TIER3", default = 0.50),
}

# Production hardening. Local mode runs over plain HTTP, so these are gated.
if CUTIEE_ENV == "production":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default = True)
    # Default to 1 year (preload-eligible). Operators can lower this via
    # DJANGO_SECURE_HSTS_SECONDS during the initial rollout to avoid
    # accidentally pinning HTTPS for a year on a misconfigured host.
    SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default = 60 * 60 * 24 * 365)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default = True)
    SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default = SECURE_HSTS_SECONDS >= 31536000)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = False  # HTMX needs JS access to read the CSRF cookie
    CSRF_COOKIE_SAMESITE = "Lax"
    X_FRAME_OPTIONS = "DENY"

# Logging — structured enough for Render's log drain.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": env("DJANGO_LOG_LEVEL", default = "INFO"),
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", default = "INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "cutiee": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
