"""Test settings — isolated and fast, requiring no external services.

Uses an in-memory SQLite database and runs Celery tasks eagerly so unit tests do
not depend on PostgreSQL, Redis, or MinIO. Integration tests that require real
backends select ``config.settings.local`` (or a dedicated CI settings module)
once pgvector-backed models exist (Sprint 5).
"""

from __future__ import annotations

from config.settings.base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = "test-insecure-key"  # noqa: S105
MCP_ENABLED = True
METRICS_BEARER_TOKEN = "test-metrics-token"  # noqa: S105

ALLOWED_HOSTS = ["testserver", "localhost"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

# Run tasks synchronously in-process; no broker needed.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Fast, deterministic password hashing for tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# In-memory cache so tests do not touch Redis.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
}

# Hermetic object store so document-plane tests exercise upload/purge without MinIO.
DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
