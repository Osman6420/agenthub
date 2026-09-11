"""Operational health probes.

- ``live``  — process liveness; constant-time, always 200 while the process runs.
- ``ready`` — dependency readiness; returns 503 if a required dependency is down.

Security: these endpoints are unauthenticated by design (used by orchestrators
and load balancers). They must expose only coarse ``ok``/``error`` status per
dependency and never leak exception text, connection strings, or secrets. Full
readiness (secret resolver, model gateway) is expanded in Sprint 7.
"""

from __future__ import annotations

import logging

import redis
from django.conf import settings
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import OperationalError
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger(__name__)

# Short timeout so a hung dependency cannot stall the readiness probe.
_REDIS_TIMEOUT_SECONDS = 2


def live(request: HttpRequest) -> JsonResponse:
    """Liveness probe: the process is up and able to serve requests."""
    return JsonResponse({"status": "ok"})


def _check_database() -> bool:
    try:
        connections["default"].cursor().execute("SELECT 1")
    except OperationalError:
        logger.warning("readiness: database check failed", exc_info=True)
        return False
    return True


def _check_migrations() -> bool:
    try:
        connection = connections["default"]
        executor = MigrationExecutor(connection)
        return not executor.migration_plan(executor.loader.graph.leaf_nodes())
    except (OperationalError, ValueError):
        logger.warning("readiness: migration check failed", exc_info=True)
        return False


def _check_redis() -> bool:
    try:
        client = redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
            socket_timeout=_REDIS_TIMEOUT_SECONDS,
        )
        client.ping()
    except (redis.RedisError, OSError):
        logger.warning("readiness: redis check failed", exc_info=True)
        return False
    return True


def ready(request: HttpRequest) -> JsonResponse:
    """Readiness probe: required dependencies are reachable.

    Returns 200 when every check passes, otherwise 503. Only coarse per-check
    status is exposed; diagnostic detail is logged server-side.
    """
    checks = {
        "database": "ok" if _check_database() else "error",
        "migrations": "ok" if _check_migrations() else "error",
        "redis": "ok" if _check_redis() else "error",
    }
    healthy = all(value == "ok" for value in checks.values())
    return JsonResponse(
        {"status": "ready" if healthy else "not_ready", "checks": checks},
        status=200 if healthy else 503,
    )
