"""Least-privilege resolution of ``secret:<name>`` references.

AgentHub stores only a logical reference; the real credential is injected at runtime
and is never persisted, logged, or returned in audit/telemetry. The preferred
production source is a corporate secret manager via the OpenShift External Secrets
Operator (v3 plan §17 approved decisions). The default resolver here reads from the
process environment as ``TOOL_SECRET_<UPPER_NAME>`` (a reviewed injection mechanism,
not source-controlled), and fails closed when a reference cannot be resolved.
"""

from __future__ import annotations

import os
from typing import Protocol

from apps.artifacts.secrets import SECRET_REFERENCE_PREFIX

_MAX_NAME_LENGTH = 128


class SecretResolutionError(RuntimeError):
    """Raised when a secret reference is malformed or cannot be resolved."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SecretResolver(Protocol):
    def resolve(self, ref: str) -> str: ...


def _secret_name(ref: str) -> str:
    if (
        not isinstance(ref, str)
        or not ref.startswith(SECRET_REFERENCE_PREFIX)
        or len(ref) <= len(SECRET_REFERENCE_PREFIX)
    ):
        raise SecretResolutionError("SECRET_REF_INVALID")
    name = ref[len(SECRET_REFERENCE_PREFIX) :]
    if len(name) > _MAX_NAME_LENGTH or not all(
        character.isalnum() or character in "._-" for character in name
    ):
        raise SecretResolutionError("SECRET_REF_INVALID")
    return name


class EnvSecretResolver:
    """Reads ``secret:<name>`` from ``TOOL_SECRET_<UPPER_NAME>`` in the environment."""

    def resolve(self, ref: str) -> str:
        name = _secret_name(ref)
        env_key = "TOOL_SECRET_" + name.upper().replace("-", "_").replace(".", "_")
        value = os.environ.get(env_key)
        if not value:
            # Deliberately reveals only the stable code, never the name or value.
            raise SecretResolutionError("SECRET_UNAVAILABLE")
        return value
