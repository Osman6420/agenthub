"""Bounded, cryptographically random allocation for console-owned identifiers."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from django.utils.text import slugify

_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
DEFAULT_SUFFIX_LENGTH = 10
MAX_ALLOCATION_ATTEMPTS = 8
_TURKISH_ASCII = str.maketrans(
    {
        "\u00e7": "c",
        "\u011f": "g",
        "\u0131": "i",
        "\u00f6": "o",
        "\u015f": "s",
        "\u00fc": "u",
        "\u00c7": "C",
        "\u011e": "G",
        "\u0130": "I",
        "\u00d6": "O",
        "\u015e": "S",
        "\u00dc": "U",
    }
)


class IdentifierAllocationError(ValueError):
    """A content-free allocation failure suitable for an operator response."""

    code = "IDENTIFIER_ALLOCATION_EXHAUSTED"


def normalized_prefix(value: str, *, fallback: str) -> str:
    """Return an ASCII slug prefix, including for punctuation/emoji-only input."""
    normalized = (value or "").strip().translate(_TURKISH_ASCII)
    return slugify(normalized, allow_unicode=False) or fallback


def allocate_identifier(
    value: str,
    *,
    fallback: str,
    max_length: int,
    exists: Callable[[str], bool],
    suffix_length: int = DEFAULT_SUFFIX_LENGTH,
    attempts: int = MAX_ALLOCATION_ATTEMPTS,
) -> str:
    """Allocate a normalized prefix plus suffix after a bounded collision check."""
    prefix = normalized_prefix(value, fallback=fallback)
    prefix = prefix[: max_length - suffix_length - 1].rstrip("-") or fallback
    for _attempt in range(attempts):
        suffix = "".join(secrets.choice(_ALPHABET) for _ in range(suffix_length))
        candidate = f"{prefix}-{suffix}"
        if not exists(candidate):
            return candidate
    raise IdentifierAllocationError


def allocate_scenario_alias(
    project_slug: str,
    scenario_slug: str,
    *,
    exists: Callable[[str], bool],
) -> str:
    """Allocate the required ``project-scenario-xxxx`` organization alias."""
    project_prefix = normalized_prefix(project_slug, fallback="project")
    scenario_prefix = normalized_prefix(scenario_slug, fallback="scenario")
    prefix = f"{project_prefix}-{scenario_prefix}"
    return allocate_identifier(
        prefix,
        fallback="project-scenario",
        max_length=128,
        exists=exists,
        suffix_length=4,
    )
