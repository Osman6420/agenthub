"""Disposable settings for the Phase 2.9 real-browser quality gate."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import environ
from django.core.exceptions import ImproperlyConfigured

from config.settings.base import *  # noqa: F401,F403

DEBUG = True
SECRET_KEY = "browser-gate-insecure-test-key"  # noqa: S105
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
AI_AUTHORING_MODEL_PROFILE_ID = None
AI_AUTHORING_PROVIDER = ""
RUNTIME_MODEL_PROVIDER = ""
RUNTIME_EMBEDDING_PROVIDER = ""
INGESTION_VECTOR_STORAGE_LAYOUT = "legacy"
OPENAI_COMPAT_ENABLED = True
RUNTIME_RETRIEVAL_PROVIDER = "apps.retrieval.providers.DemoRetrievalProvider"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

database_url = os.environ.get("BROWSER_GATE_DATABASE_URL", "").strip()
sqlite_path = os.environ.get("BROWSER_GATE_SQLITE_PATH", "").strip()
if database_url:
    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/")
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("browser gate requires PostgreSQL or guarded SQLite")
    if parsed.hostname not in {"127.0.0.1", "localhost", "postgres"}:
        raise ImproperlyConfigured("browser gate database host must be local/disposable")
    if not database_name.startswith("agenthub_browser_gate"):
        raise ImproperlyConfigured("browser gate database name must use test-only prefix")
    DATABASES = {"default": environ.Env.db_url_config(database_url)}
elif sqlite_path:
    resolved = Path(sqlite_path).resolve()
    workspace = Path(__file__).resolve().parents[2]
    allowed_root = (workspace / ".tmp").resolve()
    if allowed_root not in resolved.parents or not resolved.name.startswith(
        "agenthub_browser_gate_"
    ):
        raise ImproperlyConfigured("browser gate SQLite path must be a unique .tmp fixture")
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(resolved)}}
else:
    raise ImproperlyConfigured("explicit disposable browser gate database is required")
