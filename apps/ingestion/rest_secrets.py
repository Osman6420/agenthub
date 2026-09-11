from __future__ import annotations

import os

from apps.tools.secrets_resolver import SecretResolutionError, _secret_name


class RestPullEnvSecretResolver:
    """Resolve governed REST credentials from deployment-injected environment values."""

    def resolve(self, ref: str) -> str:
        name = _secret_name(ref)
        key = "REST_PULL_SECRET_" + name.upper().replace("-", "_").replace(".", "_")
        value = os.environ.get(key)
        if not value:
            raise SecretResolutionError("SECRET_UNAVAILABLE")
        return value
