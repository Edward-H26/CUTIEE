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


def _envStr(key: str, default: str = "") -> str:
    """Read a string env var. Typed as `str`, unlike `environ.Env.__call__`.

    `django-environ` declares its `default` kwarg as the internal
    `NoValue` sentinel, which makes every typed call emit a Pyright
    warning. Every callsite here is a plain string read, so we route
    through `os.environ.get`, which is typed as `str | None` and
    collapses cleanly to `str` with a default.
    """
    value = os.environ.get(key)
    return value if value is not None else default


_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _envBool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in _TRUTHY


def _envList(key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _envInt(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _envFloat(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


CUTIEE_ENV = _envStr("CUTIEE_ENV")
if CUTIEE_ENV not in {"local", "production"}:
    raise RuntimeError(
        "CUTIEE_ENV must be set to 'local' or 'production'. See .env.example."
    )

for required_key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    if not _envStr(required_key):
        raise RuntimeError(
            f"{required_key} is required. Google OAuth is the primary auth flow. "
            "Create credentials at https://console.cloud.google.com/apis/credentials."
        )

if CUTIEE_ENV == "production" and not _envStr("GEMINI_API_KEY"):
    raise RuntimeError("GEMINI_API_KEY required when CUTIEE_ENV=production.")

if not _envStr("NEO4J_BOLT_URL") and _envStr("NEO4J_URI"):
    # Back-compat for miramemoria-style .env files that use NEO4J_URI.
    os.environ["NEO4J_BOLT_URL"] = _envStr("NEO4J_URI")

for required_key in ("NEO4J_BOLT_URL", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
    if not _envStr(required_key):
        raise RuntimeError(
            f"{required_key} is required. Neo4j is the default database. "
            "Start it locally via `./scripts/neo4j_up.sh`, or set AuraDB "
            "credentials for production. NEO4J_URI is also accepted."
        )

SECRET_KEY = _envStr("DJANGO_SECRET_KEY", "cutiee-insecure-dev-only-change-me")
if CUTIEE_ENV == "production" and SECRET_KEY.startswith("cutiee-insecure"):
    raise RuntimeError(
        "DJANGO_SECRET_KEY must be set to a long random value when CUTIEE_ENV=production. "
        "Render's `generateValue: true` produces a suitable secret automatically."
    )

# Render injects RENDER_EXTERNAL_HOSTNAME (for example "cutiee-1kqk.onrender.com")
# on every web service. Treat its presence as the production signal so the deploy
# survives a misconfigured CUTIEE_ENV: DEBUG defaults to False, the assigned
# hostname is appended to ALLOWED_HOSTS, and the matching https origin is added
# to CSRF_TRUSTED_ORIGINS. Explicit env vars still win when set.
RENDER_EXTERNAL_HOSTNAME = _envStr("RENDER_EXTERNAL_HOSTNAME")
IS_ON_RENDER = bool(RENDER_EXTERNAL_HOSTNAME)

DEBUG = _envBool(
    "DJANGO_DEBUG",
    default = CUTIEE_ENV == "local" and not IS_ON_RENDER,
)
ALLOWED_HOSTS = _envList(
    "DJANGO_ALLOWED_HOSTS",
    default = ["localhost", "127.0.0.1"],
)
CSRF_TRUSTED_ORIGINS = _envList(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default = [],
)
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    renderOrigin = f"https://{RENDER_EXTERNAL_HOSTNAME}"
    if renderOrigin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(renderOrigin)

# Render terminates TLS at its edge and forwards plain HTTP to the
# dyno with X-Forwarded-Proto set. Without SECURE_PROXY_SSL_HEADER,
# Django believes every request is insecure, which rejects OAuth
# redirects with "CSRF verification failed" and makes session cookies
# never flag Secure. Scoping this to when IS_ON_RENDER prevents local
# dev from trusting an arbitrary X-Forwarded-Proto header.
if IS_ON_RENDER:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Accept every `*.onrender.com` PR preview as a trusted CSRF origin
    # so preview environments do not return 403 on POSTs. Revoke this
    # if you later run CUTIEE behind a non-Render hostname.
    _WILDCARD_RENDER = "https://*.onrender.com"
    if _WILDCARD_RENDER not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_WILDCARD_RENDER)

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
                "cutiee_site.context_processors.runtime",
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

NEO4J_BOLT_URL = _envStr("NEO4J_BOLT_URL")
NEO4J_USERNAME = _envStr("NEO4J_USERNAME")
NEO4J_PASSWORD = _envStr("NEO4J_PASSWORD")
NEO4J_DATABASE = _envStr("NEO4J_DATABASE", "neo4j")

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
ACCOUNT_EMAIL_VERIFICATION = _envStr("ACCOUNT_EMAIL_VERIFICATION", "optional")
ACCOUNT_EMAIL_NOTIFICATIONS = _envBool("ACCOUNT_EMAIL_NOTIFICATIONS", default = False)

# Email backend defaults to the console in dev so signup never blocks on
# an SMTP connection. Production sets DJANGO_EMAIL_BACKEND explicitly.
EMAIL_BACKEND = _envStr(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = _envStr("DJANGO_DEFAULT_FROM_EMAIL", "no-reply@cutiee.local")

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": _envStr("GOOGLE_CLIENT_ID"),
            "secret": _envStr("GOOGLE_CLIENT_SECRET"),
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

CUTIEE_RECENCY_WINDOW = _envInt("CUTIEE_RECENCY_WINDOW", 3)
CUTIEE_TEMPLATE_MATCH_THRESHOLD = _envFloat("CUTIEE_TEMPLATE_MATCH_THRESHOLD", 0.85)
CUTIEE_CONFIDENCE_THRESHOLDS = {
    1: _envFloat("CUTIEE_CONFIDENCE_THRESHOLD_TIER1", 0.75),
    2: _envFloat("CUTIEE_CONFIDENCE_THRESHOLD_TIER2", 0.65),
    3: _envFloat("CUTIEE_CONFIDENCE_THRESHOLD_TIER3", 0.50),
}

# Production hardening. Local mode runs over plain HTTP, so these are gated.
if CUTIEE_ENV == "production":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = _envBool("DJANGO_SECURE_SSL_REDIRECT", default = True)
    # Default to 1 year (preload-eligible). Operators can lower this via
    # DJANGO_SECURE_HSTS_SECONDS during the initial rollout to avoid
    # accidentally pinning HTTPS for a year on a misconfigured host.
    SECURE_HSTS_SECONDS = _envInt("DJANGO_SECURE_HSTS_SECONDS", 60 * 60 * 24 * 365)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _envBool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default = True)
    SECURE_HSTS_PRELOAD = _envBool("DJANGO_SECURE_HSTS_PRELOAD", default = SECURE_HSTS_SECONDS >= 31536000)
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
            "level": _envStr("DJANGO_LOG_LEVEL", "INFO"),
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": _envStr("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "cutiee": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
