"""Local development settings.

Convenient but never used in production. An insecure default SECRET_KEY is
allowed here only so a fresh checkout boots without extra setup.
"""

from __future__ import annotations

from config.settings.base import *  # noqa: F401,F403
from config.settings.base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="dev-insecure-key-do-not-use-in-production",  # noqa: S105
)

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1", "0.0.0.0"],  # noqa: S104
)

# Local-only convenience: allow the Django Admin route for debugging. It is never
# the management surface (ADR-0001) and stays off in production.
ENABLE_DJANGO_ADMIN = env.bool("ENABLE_DJANGO_ADMIN", default=True)

# Local product testing exposes the additive compatibility routes. Production
# inherits the disabled-by-default base setting unless explicitly enabled.
OPENAI_COMPAT_ENABLED = env.bool("OPENAI_COMPAT_ENABLED", default=True)
