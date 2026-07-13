from __future__ import annotations

import os

from apps.tools.secrets_resolver import SecretResolutionError, _secret_name


class ConfluenceEnvSecretResolver:
    """Resolve Confluence PAT references from deployment-injected environment values."""

    def resolve(self, ref: str) -> str:
        name = _secret_name(ref)
        key = "CONFLUENCE_SECRET_" + name.upper().replace("-", "_").replace(".", "_")
        value = os.environ.get(key)
        if not value:
            raise SecretResolutionError("SECRET_UNAVAILABLE")
        return value
