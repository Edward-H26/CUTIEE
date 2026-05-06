"""Django settings for CUTIEE.

Domain data lives in Neo4j. Production framework auth, sessions, and
preferences also use Neo4j; Django's SQL backend remains configured only as
an unused framework placeholder. Local mode keeps Django's ORM auth path for
tests and developer convenience.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
IS_PYTEST = any("pytest" in Path(arg).name for arg in sys.argv)

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
    raise RuntimeError("CUTIEE_ENV must be set to 'local' or 'production'. See .env.example.")

GOOGLE_CLIENT_ID = _envStr("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _envStr("GOOGLE_CLIENT_SECRET")

for required_key, value in (
    ("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID),
    ("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET),
):
    if not value:
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
CUTIEE_NEO4J_FRAMEWORK_AUTH = (
    CUTIEE_ENV == "production"
    and not IS_PYTEST
    and _envBool("CUTIEE_NEO4J_FRAMEWORK_AUTH", default=True)
)

DEBUG = _envBool(
    "DJANGO_DEBUG",
    default=CUTIEE_ENV == "local" and not IS_ON_RENDER,
)
ALLOWED_HOSTS = _envList(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1"],
)
CSRF_TRUSTED_ORIGINS = _envList(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=[],
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

_DJANGO_FRAMEWORK_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
]

if not CUTIEE_NEO4J_FRAMEWORK_AUTH:
    _DJANGO_FRAMEWORK_APPS = [
        "django.contrib.admin",
        *_DJANGO_FRAMEWORK_APPS,
        "django.contrib.sessions",
        "django.contrib.sites",
        "allauth",
        "allauth.account",
        "allauth.socialaccount",
        "allauth.socialaccount.providers.google",
    ]

INSTALLED_APPS = [
    *_DJANGO_FRAMEWORK_APPS,
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
    (
        "apps.accounts.neo4j_auth.Neo4jAuthenticationMiddleware"
        if CUTIEE_NEO4J_FRAMEWORK_AUTH
        else "django.contrib.auth.middleware.AuthenticationMiddleware"
    ),
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if not CUTIEE_NEO4J_FRAMEWORK_AUTH:
    MIDDLEWARE.append("allauth.account.middleware.AccountMiddleware")

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
                (
                    "apps.accounts.context_processors.auth"
                    if CUTIEE_NEO4J_FRAMEWORK_AUTH
                    else "django.contrib.auth.context_processors.auth"
                ),
                "django.contrib.messages.context_processors.messages",
                "cutiee_site.context_processors.runtime",
                "cutiee_site.context_processors.userTheme",
            ],
        },
    },
]

WSGI_APPLICATION = "cutiee_site.wsgi.application"
ASGI_APPLICATION = "cutiee_site.asgi.application"


def _localDatabaseConfig() -> dict[str, Any]:
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "file:cutiee_internals?mode=memory&cache=shared",
        "OPTIONS": {"uri": True, "transaction_mode": "IMMEDIATE"},
    }


def _databaseConfigFromUrl(rawUrl: str) -> dict[str, Any]:
    parsed = urlparse(rawUrl)
    scheme = parsed.scheme.lower()
    if scheme in {"postgres", "postgresql", "postgresql+psycopg"}:
        config: dict[str, Any] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
        }
        query = parse_qs(parsed.query)
        sslMode = query.get("sslmode", [""])[0]
        if sslMode:
            config["OPTIONS"] = {"sslmode": sslMode}
        return config
    if scheme == "sqlite":
        name = unquote(parsed.path or "")
        if parsed.netloc:
            name = f"/{parsed.netloc}{name}"
        if name == "/:memory:":
            name = ":memory:"
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": name,
        }
    raise RuntimeError("DJANGO_DATABASE_URL must use postgres://, postgresql://, or sqlite://.")


def _productionDatabaseConfig() -> dict[str, Any]:
    if IS_PYTEST or CUTIEE_NEO4J_FRAMEWORK_AUTH:
        return _localDatabaseConfig()
    rawUrl = _envStr("DJANGO_DATABASE_URL") or _envStr("DATABASE_URL")
    if not rawUrl:
        raise RuntimeError(
            "DJANGO_DATABASE_URL or DATABASE_URL is only required in production when "
            "CUTIEE_NEO4J_FRAMEWORK_AUTH=false. Set CUTIEE_NEO4J_FRAMEWORK_AUTH=true "
            "to keep framework auth, sessions, and preferences in Neo4j."
        )
    return _databaseConfigFromUrl(rawUrl)


DATABASES = {
    "default": _productionDatabaseConfig()
    if CUTIEE_ENV == "production"
    else _localDatabaseConfig(),
}

NEO4J_BOLT_URL = _envStr("NEO4J_BOLT_URL")
NEO4J_USERNAME = _envStr("NEO4J_USERNAME")
NEO4J_PASSWORD = _envStr("NEO4J_PASSWORD")
NEO4J_DATABASE = _envStr("NEO4J_DATABASE", "neo4j")

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]
if not CUTIEE_NEO4J_FRAMEWORK_AUTH:
    AUTHENTICATION_BACKENDS.append("allauth.account.auth_backends.AuthenticationBackend")

SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_ENGINE = (
    "cutiee_site.neo4j_session_backend"
    if CUTIEE_NEO4J_FRAMEWORK_AUTH
    else "django.contrib.sessions.backends.db"
)
MESSAGE_STORAGE = (
    "django.contrib.messages.storage.cookie.CookieStorage"
    if CUTIEE_NEO4J_FRAMEWORK_AUTH
    else "django.contrib.messages.storage.fallback.FallbackStorage"
)

SITE_ID = 1
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/tasks/"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = _envStr("ACCOUNT_EMAIL_VERIFICATION", "optional")
ACCOUNT_EMAIL_NOTIFICATIONS = _envBool("ACCOUNT_EMAIL_NOTIFICATIONS", default=False)

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
            "client_id": GOOGLE_CLIENT_ID,
            "secret": GOOGLE_CLIENT_SECRET,
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
    SECURE_SSL_REDIRECT = _envBool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    # Default to 1 year (preload-eligible). Operators can lower this via
    # DJANGO_SECURE_HSTS_SECONDS during the initial rollout to avoid
    # accidentally pinning HTTPS for a year on a misconfigured host.
    SECURE_HSTS_SECONDS = _envInt("DJANGO_SECURE_HSTS_SECONDS", 60 * 60 * 24 * 365)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _envBool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
    SECURE_HSTS_PRELOAD = _envBool(
        "DJANGO_SECURE_HSTS_PRELOAD", default=SECURE_HSTS_SECONDS >= 31536000
    )
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
# Set `LOGGING_FORMAT=json` to emit one JSON object per record. The JSON
# formatter is hand-rolled (no extra dep) and produces fields that play
# nicely with Render's log drain, Loki / Grafana queries, and Sentry's
# breadcrumb capture.
_LOGGING_FORMAT = _envStr("LOGGING_FORMAT", "verbose").lower()
_DEFAULT_FORMATTER = "json" if _LOGGING_FORMAT == "json" else "verbose"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
        "json": {
            "()": "cutiee_site.logging_filters.JsonLogFormatter",
        },
    },
    "handlers": {
        "console": {
            "level": _envStr("DJANGO_LOG_LEVEL", "INFO"),
            "class": "logging.StreamHandler",
            "formatter": _DEFAULT_FORMATTER,
        },
    },
    "root": {"handlers": ["console"], "level": _envStr("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "cutiee": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Sentry. Optional dep; activates only when SENTRY_DSN is set AND the
# `sentry-sdk` package is installed. This keeps the local dev path
# zero-friction while making production-side error capture a one-line
# pip install away. Sample rate is conservative because CUTIEE runs are
# long-lived and traces would dominate the budget otherwise.
SENTRY_DSN = _envStr("SENTRY_DSN")
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[
                DjangoIntegration(),
                LoggingIntegration(level=None, event_level=None),
            ],
            traces_sample_rate=_envFloat("SENTRY_TRACES_SAMPLE_RATE", 0.05),
            send_default_pii=False,
            release=_envStr("RENDER_GIT_COMMIT") or "cutiee@dev",
            environment=CUTIEE_ENV,
        )
    except ImportError:
        pass

# Prometheus exporter, off by default. Enable with
# CUTIEE_ENABLE_PROMETHEUS=1 and ensure `prometheus-client` is installed
# (e.g. `uv pip install prometheus-client`). When enabled, the
# `/metrics/` view returns Prometheus text format with cost, execution,
# and Gemini call metrics exposed by `agent/persistence/metrics.py`.
CUTIEE_ENABLE_PROMETHEUS = _envBool("CUTIEE_ENABLE_PROMETHEUS", default=False)
