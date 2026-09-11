"""Production settings — fail closed on missing secrets, enforce transport security.

Required environment variables (no defaults): ``DJANGO_SECRET_KEY`` and
``DJANGO_ALLOWED_HOSTS``, plus a matching ``AGENTHUB_STATIC_RELEASE_ID`` and
``DJANGO_STATIC_URL``. The immutable application image supplies ``AGENTHUB_IMAGE_RELEASE_ID``.
If any are missing or inconsistent, startup raises immediately so a misconfigured deployment never
serves traffic with an insecure or mismatched frontend.
"""

from __future__ import annotations

import re

from django.core.exceptions import ImproperlyConfigured

from config.settings.base import *  # noqa: F401,F403
from config.settings.base import env

DEBUG = False

# ImproperlyConfigured is raised by django-environ if these are unset.
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# The static image is built under this exact release prefix. Requiring the URL to match prevents a
# web rollout from referencing another release's fixed-name builder.js/builder.css files.
STATIC_RELEASE_ID = env("AGENTHUB_STATIC_RELEASE_ID")
if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", STATIC_RELEASE_ID):
    raise ImproperlyConfigured("AGENTHUB_STATIC_RELEASE_ID must match [A-Za-z0-9._-]{1,128}.")
IMAGE_RELEASE_ID = env("AGENTHUB_IMAGE_RELEASE_ID")
if IMAGE_RELEASE_ID != STATIC_RELEASE_ID:
    raise ImproperlyConfigured("AGENTHUB_IMAGE_RELEASE_ID must match AGENTHUB_STATIC_RELEASE_ID.")
STATIC_URL = env("DJANGO_STATIC_URL")
_expected_static_url = f"/static/{STATIC_RELEASE_ID}/"
if STATIC_URL != _expected_static_url:
    raise ImproperlyConfigured(
        f"DJANGO_STATIC_URL must equal {_expected_static_url!r} for this release."
    )

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
