"""Base settings shared by all environments.

Configuration is environment-driven (12-factor) via ``django-environ``. Secrets
are read from the environment only and never hard-coded here. Environment-specific
files (local/test/production) import from this module and override safely.
"""

from __future__ import annotations

from pathlib import Path

import environ

# config/settings/base.py -> repo root is three parents up.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

# Read a .env file if present (developer convenience; never committed).
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    env.read_env(str(_env_file))

# --- Core -------------------------------------------------------------------
# SECRET_KEY has no default here; environment files decide whether an insecure
# development default is acceptable. production.py requires a real value.
SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# --- Applications -----------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
]

# Domain apps are added per sprint as they are implemented (see the v3 plan §5.2).
LOCAL_APPS = [
    "apps.tenancy",
    "apps.identity",
    "apps.catalog",
    "apps.artifacts",
    "apps.releases",
    "apps.retrieval",
    "apps.ingestion",
    "apps.orchestration",
    "apps.workflows",
    "apps.tools",
    "apps.evaluations",
    "apps.observability",
    "apps.mcp",
    "apps.audit",
    "apps.gateway",
    "apps.console",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.gateway.middleware.RequestIDMiddleware",
    "apps.observability.middleware.TelemetryMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------
# DATABASE_URL selects the backend, e.g.
#   postgres://user:pass@host:5432/agenthub
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://agenthub:agenthub@localhost:5432/agenthub",
    ),
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Cache / Redis / Celery -------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    },
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 60 * 30
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 25

# --- Gateway / DRF ----------------------------------------------------------
REST_FRAMEWORK = {
    # Consumers authenticate with a bearer token; humans never use this API.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.gateway.authentication.ConsumerTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "apps.gateway.permissions.HasActiveConsumer",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.gateway.throttling.ConsumerRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "consumer": env("GATEWAY_CONSUMER_RATE", default="120/min"),
    },
    "EXCEPTION_HANDLER": "apps.gateway.errors.exception_handler",
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# Signed ExecutionContext lifetime and request body ceiling.
EXECUTION_CONTEXT_TTL_SECONDS = env.int("EXECUTION_CONTEXT_TTL_SECONDS", default=300)
GATEWAY_MAX_REQUEST_BYTES = env.int("GATEWAY_MAX_REQUEST_BYTES", default=1_000_000)

# --- MCP / telemetry (Sprint 7) --------------------------------------------
MCP_ENABLED = env.bool("MCP_ENABLED", default=False)
MCP_MAX_REQUEST_BYTES = env.int("MCP_MAX_REQUEST_BYTES", default=1_000_000)
MCP_MAX_NESTING_DEPTH = env.int("MCP_MAX_NESTING_DEPTH", default=12)
MCP_PROTOCOL_VERSION = env("MCP_PROTOCOL_VERSION", default="2025-06-18")
MCP_ALLOWED_ORIGINS = env.list("MCP_ALLOWED_ORIGINS", default=[])
METRICS_ENABLED = env.bool("METRICS_ENABLED", default=True)
METRICS_BEARER_TOKEN = env("METRICS_BEARER_TOKEN", default="")
OTEL_SERVICE_NAME = env("OTEL_SERVICE_NAME", default="agenthub-web")
OTEL_EXPORTER_OTLP_ENDPOINT = env("OTEL_EXPORTER_OTLP_ENDPOINT", default="")
OTEL_EXPORTER_OTLP_ALLOWED_HOSTS = env.list("OTEL_EXPORTER_OTLP_ALLOWED_HOSTS", default=[])
OTEL_TRACE_SAMPLE_RATIO = env.float("OTEL_TRACE_SAMPLE_RATIO", default=0.1)

# --- Runtime providers (Sprint 4) -------------------------------------------
# Dotted paths to the model/retrieval provider callables. Empty -> deterministic
# built-in defaults (stub model, static retriever). The real OpenAI-compatible model
# provider and pgvector retriever plug in here without code changes.
RUNTIME_MODEL_PROVIDER = env("RUNTIME_MODEL_PROVIDER", default="")
RUNTIME_RETRIEVAL_PROVIDER = env(
    "RUNTIME_RETRIEVAL_PROVIDER",
    default="apps.retrieval.providers.PgvectorRetrievalProvider",
)

# --- Object storage (S3/MinIO) ----------------------------------------------
# Referenced by ingestion (Sprint 5). Declared here so config is validated early.
OBJECT_STORE = {
    "endpoint_url": env("OBJECT_STORE_ENDPOINT", default=""),
    "bucket": env("OBJECT_STORE_BUCKET", default="agenthub"),
    "region": env("OBJECT_STORE_REGION", default="us-east-1"),
}

INGESTION_HTTP_ALLOWED_HOSTS = env.list("INGESTION_HTTP_ALLOWED_HOSTS", default=[])
INGESTION_MAX_SOURCE_BYTES = env.int("INGESTION_MAX_SOURCE_BYTES", default=10_000_000)
INGESTION_HTTP_TIMEOUT_SECONDS = env.int("INGESTION_HTTP_TIMEOUT_SECONDS", default=15)
INGESTION_EMBEDDING_DIMENSIONS = 64

# --- Authentication / operator console (ADR-0001) ---------------------------
# The operator console is the management surface, not Django Admin. Human operators
# authenticate via LDAP in production; when LDAP is disabled (dev/CI/test) the
# Django model backend authenticates local accounts so the console stays testable.
LOGIN_URL = "console:login"
LOGIN_REDIRECT_URL = "console:dashboard"
LOGOUT_REDIRECT_URL = "console:login"

# Django Admin is off by default and never routed in production; it may be enabled
# only as a local debugging convenience.
ENABLE_DJANGO_ADMIN = env.bool("ENABLE_DJANGO_ADMIN", default=False)

AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

LDAP_ENABLED = env.bool("LDAP_ENABLED", default=False)
if LDAP_ENABLED:
    # Imported only when enabled so python-ldap/django-auth-ldap are not required
    # in environments without a directory (local dev, CI, tests).
    import ldap  # noqa: F401
    from django_auth_ldap.config import GroupOfNamesType, LDAPSearch

    AUTH_LDAP_SERVER_URI = env("LDAP_SERVER_URI")  # ldaps://dc.corp.example:636
    AUTH_LDAP_BIND_DN = env("LDAP_BIND_DN")
    AUTH_LDAP_BIND_PASSWORD = env("LDAP_BIND_PASSWORD")
    AUTH_LDAP_USER_SEARCH = LDAPSearch(
        env("LDAP_USER_SEARCH_BASE"),
        ldap.SCOPE_SUBTREE,
        env("LDAP_USER_FILTER", default="(sAMAccountName=%(user)s)"),
    )
    AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
        env("LDAP_GROUP_SEARCH_BASE"),
        ldap.SCOPE_SUBTREE,
        env("LDAP_GROUP_FILTER", default="(objectClass=group)"),
    )
    AUTH_LDAP_GROUP_TYPE = GroupOfNamesType(name_attr="cn")
    AUTH_LDAP_USER_ATTR_MAP = {
        "first_name": "givenName",
        "last_name": "sn",
        "email": "mail",
    }
    # Directory group -> Django flags. Fine-grained role mapping to AgentHub roles
    # is applied on top of this in the identity app.
    AUTH_LDAP_USER_FLAGS_BY_GROUP = {
        "is_staff": env("LDAP_STAFF_GROUP", default=""),
        "is_superuser": env("LDAP_SUPERUSER_GROUP", default=""),
    }
    AUTH_LDAP_ALWAYS_UPDATE_USER = True
    AUTH_LDAP_MIRROR_GROUPS = True
    # LDAPS with certificate validation; fail closed on bad certs.
    AUTH_LDAP_CONNECTION_OPTIONS = {ldap.OPT_X_TLS_REQUIRE_CERT: ldap.OPT_X_TLS_DEMAND}

    AUTHENTICATION_BACKENDS = [
        "django_auth_ldap.backend.LDAPBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]

# --- Password validation ----------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- I18N / time ------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static -----------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Logging ----------------------------------------------------------------
# Structured, stable log records. Sensitive data (PII, secrets, raw prompts,
# raw documents, tool inputs) must never be written to logs (observability rules).
# A richer JSON formatter + request/trace-id propagation arrives in Sprint 7.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": ("level=%(levelname)s logger=%(name)s time=%(asctime)s message=%(message)s"),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("DJANGO_LOG_LEVEL", default="INFO"),
    },
}
