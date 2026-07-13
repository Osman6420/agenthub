from __future__ import annotations

import os

from apps.tools.secrets_resolver import SecretResolutionError, _secret_name


class OcrEnvSecretResolver:
    def resolve(self, ref: str) -> str:
        name = _secret_name(ref)
        key = "OCR_SECRET_" + name.upper().replace("-", "_").replace(".", "_")
        value = os.environ.get(key)
        if not value:
            raise SecretResolutionError("SECRET_UNAVAILABLE")
        return value
