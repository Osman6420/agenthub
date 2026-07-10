"""Production settings — fail closed on missing secrets, enforce transport security.

Required environment variables (no defaults): ``DJANGO_SECRET_KEY`` and
``DJANGO_ALLOWED_HOSTS``. If either is missing, startup raises immediately so a
misconfigured deployment never serves traffic with an insecure default.
"""

from __future__ import annotations

from config.settings.base import *  # noqa: F401,F403
from config.settings.base import env

DEBUG = False

# ImproperlyConfigured is raised by django-environ if these are unset.
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# --- Transport / cookie security -------------------------------------------
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
