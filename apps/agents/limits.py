"""Hard resource caps for the agent runtime and per-agent limit resolution.

Model-directed loops amplify prompt injection, denial of wallet, and runaway cost, so
every run is bounded by non-negotiable caps (approved by the project owner on
2026-07-10). A pinned agent may only *lower* a limit; an attempt to raise one above a
cap is rejected at author time. Limits are part of the immutable compiled agent config,
so a run stays bounded by the exact numbers pinned into its release.
"""

from __future__ import annotations

from dataclasses import dataclass

# Non-negotiable ceilings. A per-agent override may be <= these; never above.
MAX_STEPS = 20
MAX_TOOL_CALLS = 10
MAX_TOKENS = 32_000
MAX_DEADLINE_SECONDS = 600

# Durable checkpoint size ceiling (2 MiB). A checkpoint that would exceed this fails the
# run closed rather than persisting an unbounded blob.
MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024

# Bumped only when the persisted checkpoint shape changes. A run whose checkpoint was
# written by a different schema version is never resumed on incompatible code.
CHECKPOINT_SCHEMA_VERSION = 1

_FIELD_CAPS: dict[str, int] = {
    "max_steps": MAX_STEPS,
    "max_tool_calls": MAX_TOOL_CALLS,
    "max_tokens": MAX_TOKENS,
    "deadline_seconds": MAX_DEADLINE_SECONDS,
}
# max_tool_calls may legitimately be 0 (a no-tool agent); the rest must be >= 1.
_FIELD_MINS: dict[str, int] = {
    "max_steps": 1,
    "max_tool_calls": 0,
    "max_tokens": 1,
    "deadline_seconds": 1,
}

LIMIT_FIELDS: frozenset[str] = frozenset(_FIELD_CAPS)


@dataclass(frozen=True)
class AgentLimits:
    max_steps: int = MAX_STEPS
    max_tool_calls: int = MAX_TOOL_CALLS
    max_tokens: int = MAX_TOKENS
    deadline_seconds: int = MAX_DEADLINE_SECONDS

    def as_dict(self) -> dict[str, int]:
        return {
            "max_steps": self.max_steps,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "deadline_seconds": self.deadline_seconds,
        }


class LimitError(ValueError):
    """Raised when a pinned limit override is malformed or exceeds a hard cap."""


def field_bounds(field: str) -> tuple[int, int]:
    """Return the inclusive ``(minimum, cap)`` an override for ``field`` must satisfy."""
    return _FIELD_MINS[field], _FIELD_CAPS[field]


def resolve_limits(overrides: dict[str, int] | None) -> AgentLimits:
    """Clamp validated overrides onto the caps; absent fields keep the cap default.

    ``overrides`` is trusted to already be structurally valid (author-time schema
    validation guarantees each value is a bounded int within ``field_bounds``); this
    function additionally clamps defensively so a compiled config can never exceed a cap.
    """
    values = dict(AgentLimits().as_dict())
    for field, cap in _FIELD_CAPS.items():
        if overrides and field in overrides:
            candidate = int(overrides[field])
            low, _ = field_bounds(field)
            if candidate < low or candidate > cap:
                raise LimitError(f"{field} override must be within [{low}, {cap}]")
            values[field] = candidate
    return AgentLimits(**values)
