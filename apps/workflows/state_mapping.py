"""Shared restricted JSON Pointer + typed state-mapping seam (P2.6.1).

One pure, deterministic module used identically by the workflow compiler, the release
compiler and the runtime, so a mapping accepted at author/compile time cannot be
reinterpreted differently when it executes.

The grammar is the ADR-0010 restricted absolute JSON Pointer subset:

- must be a non-empty absolute pointer (``/segment[/segment...]``);
- empty/root pointers, URI fragments, wildcards (``*``), recursive descent (``**``),
  filters, array append (``-``) and negative indexes are rejected;
- escapes are limited to the canonical ``~0`` (``~``) and ``~1`` (``/``); any other
  ``~`` sequence is invalid.

Mappings are explicit ``{"from", "to"}`` entries. They move data only; they never carry
authority. ``output_mapping`` destinations are restricted to a deny-by-default allowlist
of business namespaces so no mapping can write server-owned tenant/actor/authorization/
capability/release/execution/secret/orchestration/budget/audit state, regardless of case,
escape or Unicode-confusable spelling. There is no expression, template or code evaluation.
"""

from __future__ import annotations

import unicodedata
from copy import deepcopy
from typing import Any

MAX_POINTER_LENGTH = 256
MAX_POINTER_SEGMENTS = 12
MAX_MAPPING_ENTRIES = 24

# Deny-by-default: an ``output_mapping`` destination root must be exactly one of these
# canonical business namespaces. Everything else (including any protected root spelled with
# case/escape/confusable tricks) is denied.
ALLOWED_WRITE_ROOTS: frozenset[str] = frozenset(
    {"input", "retrieval", "branches", "evidence", "decisions", "output"}
)

# Explicit registry of server-owned namespaces, kept for clear diagnostics and tests. The
# deny-by-default allowlist above is the real gate; this list only makes obvious attempts
# report ``WORKFLOW_PATH_PROTECTED`` deterministically.
PROTECTED_WRITE_ROOTS: frozenset[str] = frozenset(
    {
        "tenant",
        "organization",
        "org",
        "actor",
        "consumer",
        "principal",
        "authorization",
        "authz",
        "capability",
        "capabilities",
        "release",
        "manifest",
        "execution",
        "execution_context",
        "context",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "token",
        "orchestration",
        "control",
        "budget",
        "audit",
        "approval",
        "policy_version",
        "awaiting_node",
        "deadline",
        "status",
    }
)


class MappingError(ValueError):
    """A safe, content-free mapping diagnostic carrying a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_pointer(value: Any) -> tuple[str, ...]:
    """Parse a restricted absolute JSON Pointer into decoded segments.

    Raises ``MappingError("WORKFLOW_PATH_INVALID")`` for every forbidden form.
    """
    if not isinstance(value, str) or not value or len(value) > MAX_POINTER_LENGTH:
        raise MappingError("WORKFLOW_PATH_INVALID")
    if value[0] != "/":
        # Root/empty pointers and fragment pointers ("#/...") are forbidden.
        raise MappingError("WORKFLOW_PATH_INVALID")
    raw_segments = value[1:].split("/")
    if not raw_segments or len(raw_segments) > MAX_POINTER_SEGMENTS:
        raise MappingError("WORKFLOW_PATH_INVALID")
    segments: list[str] = []
    for raw in raw_segments:
        if raw == "":
            # Empty segment => "//", trailing slash, or leading "/"-only pointer.
            raise MappingError("WORKFLOW_PATH_INVALID")
        if raw in {"*", "**", "-"} or "*" in raw:
            # Wildcard, recursive descent and array-append are forbidden.
            raise MappingError("WORKFLOW_PATH_INVALID")
        _reject_non_canonical_escapes(raw)
        if _is_negative_index(raw):
            raise MappingError("WORKFLOW_PATH_INVALID")
        segments.append(raw.replace("~1", "/").replace("~0", "~"))
    return tuple(segments)


def _reject_non_canonical_escapes(raw: str) -> None:
    index = 0
    while index < len(raw):
        if raw[index] == "~":
            if index + 1 >= len(raw) or raw[index + 1] not in "01":
                raise MappingError("WORKFLOW_PATH_INVALID")
            index += 2
        else:
            index += 1


def _is_negative_index(raw: str) -> bool:
    return len(raw) > 1 and raw[0] == "-" and raw[1:].isdigit()


def assert_writable_destination(segments: tuple[str, ...]) -> None:
    """Deny writes to any non-business / server-owned namespace (deny by default)."""
    root = segments[0]
    normalized = unicodedata.normalize("NFKC", root).casefold()
    if normalized in PROTECTED_WRITE_ROOTS:
        raise MappingError("WORKFLOW_PATH_PROTECTED")
    # Deny by default: only an exactly-canonical business root may be written. This alone
    # defeats case/escape/confusable spellings of a protected name because they are simply
    # not members of the small ASCII allowlist.
    if root not in ALLOWED_WRITE_ROOTS:
        raise MappingError("WORKFLOW_PATH_PROTECTED")


def compile_mappings(entries: Any, *, restrict_destination: bool) -> tuple[dict[str, str], ...]:
    """Validate and canonicalize an ``input_mapping``/``output_mapping`` list.

    ``restrict_destination`` applies the protected-namespace allowlist to ``to`` (used for
    ``output_mapping``, which writes workflow state; ``input_mapping`` targets only the
    transient node-local envelope).
    """
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_MAPPING_ENTRIES:
        raise MappingError("WORKFLOW_MAPPING_INVALID")
    compiled: list[dict[str, str]] = []
    destinations: list[tuple[str, ...]] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"from", "to"}:
            raise MappingError("WORKFLOW_MAPPING_INVALID")
        source = entry["from"]
        target = entry["to"]
        parse_pointer(source)
        target_segments = parse_pointer(target)
        if restrict_destination:
            assert_writable_destination(target_segments)
        _reject_conflict(destinations, target_segments)
        destinations.append(target_segments)
        compiled.append({"from": source, "to": target})
    return tuple(compiled)


def _reject_conflict(existing: list[tuple[str, ...]], candidate: tuple[str, ...]) -> None:
    for other in existing:
        shorter, longer = sorted((other, candidate), key=len)
        if longer[: len(shorter)] == shorter:
            # Equal, or one is an ancestor of the other => order-dependent write. Reject.
            raise MappingError("WORKFLOW_MAPPING_CONFLICT")


_MISSING = object()


def resolve_pointer(root: Any, segments: tuple[str, ...]) -> Any:
    current: Any = root
    for segment in segments:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
        else:
            raise MappingError("WORKFLOW_MAPPING_MISSING")
    return current


def set_pointer(root: dict[str, Any], segments: tuple[str, ...], value: Any) -> None:
    current: Any = root
    for segment in segments[:-1]:
        child = current.get(segment) if isinstance(current, dict) else _MISSING
        if child is _MISSING or child is None:
            child = {}
            current[segment] = child
        if not isinstance(child, dict):
            raise MappingError("WORKFLOW_MAPPING_TYPE_MISMATCH")
        current = child
    if not isinstance(current, dict):
        raise MappingError("WORKFLOW_MAPPING_TYPE_MISMATCH")
    current[segments[-1]] = value


def build_input_envelope(
    state: dict[str, Any], mappings: tuple[dict[str, str], ...] | list[dict[str, str]]
) -> dict[str, Any]:
    """Build a node-local input envelope from a snapshot of pre-node state.

    The node sees only what its ``input_mapping`` declares; ambient state is never passed.
    A missing source path fails closed before the node runs.
    """
    envelope: dict[str, Any] = {}
    for entry in mappings:
        value = resolve_pointer(state, parse_pointer(entry["from"]))
        set_pointer(envelope, parse_pointer(entry["to"]), deepcopy(value))
    return envelope


def apply_output_mapping(
    state: dict[str, Any],
    envelope: dict[str, Any],
    mappings: tuple[dict[str, str], ...] | list[dict[str, str]],
) -> dict[str, Any]:
    """Project a node's output envelope into workflow state (copy-on-success).

    Returns a new state dict; the caller adopts it only if this returns normally, so a
    failed mapping never partially mutates the run's state.
    """
    working = deepcopy(state)
    for entry in mappings:
        target = parse_pointer(entry["to"])
        assert_writable_destination(target)
        value = resolve_pointer(envelope, parse_pointer(entry["from"]))
        set_pointer(working, target, deepcopy(value))
    return working
