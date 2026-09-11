"""Inline-secret detection for artifact/GitOps bodies.

Secrets must never be embedded in an artifact. Configuration may only reference a
secret indirectly as ``secret:<logical-name>`` (v3 plan §8.4, §22.1). This scanner
rejects any secret-like key whose value is a literal rather than such a reference.
"""

from __future__ import annotations

from typing import Any

# Keys that must never carry a literal secret value.
SECRET_KEY_HINTS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "api_key",
        "apikey",
        "access_key",
        "private_key",
        "client_secret",
        "authorization",
        "bearer",
    }
)

SECRET_REFERENCE_PREFIX = "secret:"  # noqa: S105  # marker prefix, not a secret value


def _is_reference(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(SECRET_REFERENCE_PREFIX)


def find_inline_secrets(body: Any, path: str = "") -> list[str]:
    """Return the paths of any keys that appear to hold a literal secret."""
    offenders: list[str] = []
    if isinstance(body, dict):
        for key, value in body.items():
            here = f"{path}.{key}" if path else str(key)
            if str(key).lower() in SECRET_KEY_HINTS:
                if isinstance(value, str) and value and not _is_reference(value):
                    offenders.append(here)
            offenders.extend(find_inline_secrets(value, here))
    elif isinstance(body, list):
        for index, item in enumerate(body):
            offenders.extend(find_inline_secrets(item, f"{path}[{index}]"))
    return offenders


class InlineSecretError(ValueError):
    """Raised when an artifact body contains a literal secret value."""


def assert_no_inline_secrets(body: Any) -> None:
    offenders = find_inline_secrets(body)
    if offenders:
        raise InlineSecretError(
            "inline secret value(s) not allowed; use 'secret:<name>' references at: "
            + ", ".join(sorted(offenders))
        )
