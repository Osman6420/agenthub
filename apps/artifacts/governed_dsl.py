"""Closed, versioned schemas for governed transform, chunking and retrieval DSL artifacts."""

from __future__ import annotations

import json
import math
import time
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, NoReturn


class GovernedDSLValidationError(ValueError):
    """A content-free, stable validation failure safe to project to operators."""


MAX_BODY_BYTES = 64_000
MAX_STEPS = 32
MAX_EXPRESSION_DEPTH = 6
MAX_FILTER_TERMS = 32
MAX_POINTER_LENGTH = 256
MAX_STRING_LENGTH = 8_000
MAX_RECORDS = 2_000
MAX_OUTPUT_BYTES = 2_000_000
MAX_CHUNKS = 10_000
MAX_EXECUTION_SECONDS = 1.0

_FORBIDDEN_POINTER_SEGMENTS = {"__class__", "__dict__", "__proto__", "constructor", "prototype"}
_TRANSFORM_TOP_KEYS = {"api_version", "kind", "spec"}
_TRANSFORM_SPEC_KEYS = {"steps", "limits"}
_LIMIT_KEYS = {"max_records", "max_output_bytes", "max_string_length"}
_STEP_KEYS: dict[str, set[str]] = {
    "records.select": {"op", "pointer"},
    "records.filter": {"op", "where"},
    "fields.rename": {"op", "from", "to"},
    "fields.drop": {"op", "pointer"},
    "fields.default": {"op", "pointer", "value"},
    "text.normalize": {"op", "pointer", "unicode", "whitespace"},
    "text.replace": {"op", "pointer", "old", "new", "count"},
    "documents.map": {"op", "id", "title", "content", "metadata"},
}
_FILTER_KEYS = {"field", "eq", "ne", "gt", "gte", "lt", "lte", "and", "or"}


def _fail(code: str) -> NoReturn:
    raise GovernedDSLValidationError(code)


def _exact_keys(value: dict[str, Any], allowed: set[str], code: str) -> None:
    if set(value) - allowed:
        _fail(code)


def _bounded_body(body: dict[str, Any]) -> None:
    if (
        len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        > MAX_BODY_BYTES
    ):
        _fail("dsl_body_too_large")


def _pointer(value: Any) -> None:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > MAX_POINTER_LENGTH:
        _fail("dsl_pointer_invalid")
    segments = value[1:].split("/")
    if not segments or any(not segment for segment in segments):
        _fail("dsl_pointer_invalid")
    for raw in segments:
        index = 0
        while index < len(raw):
            if raw[index] == "~" and (index + 1 >= len(raw) or raw[index + 1] not in "01"):
                _fail("dsl_pointer_invalid")
            index += 2 if raw[index] == "~" else 1
        segment = raw.replace("~1", "/").replace("~0", "~")
        if segment in _FORBIDDEN_POINTER_SEGMENTS:
            _fail("dsl_pointer_forbidden")


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _filter(expression: Any, *, depth: int = 1, terms: list[int] | None = None) -> None:
    if terms is None:
        terms = [0]
    terms[0] += 1
    if depth > MAX_EXPRESSION_DEPTH or terms[0] > MAX_FILTER_TERMS:
        _fail("dsl_filter_too_complex")
    if not isinstance(expression, dict) or not expression:
        _fail("dsl_filter_invalid")
    _exact_keys(expression, _FILTER_KEYS, "dsl_filter_unknown_field")
    boolean_keys = [key for key in ("and", "or") if key in expression]
    comparison_keys = [key for key in ("eq", "ne", "gt", "gte", "lt", "lte") if key in expression]
    if boolean_keys:
        if len(boolean_keys) != 1 or len(expression) != 1 or comparison_keys:
            _fail("dsl_filter_invalid")
        children = expression[boolean_keys[0]]
        if not isinstance(children, list) or not 1 <= len(children) <= 8:
            _fail("dsl_filter_invalid")
        for child in children:
            _filter(child, depth=depth + 1, terms=terms)
        return
    if set(expression) != {"field", *comparison_keys} or len(comparison_keys) != 1:
        _fail("dsl_filter_invalid")
    _pointer(expression["field"])
    compared = expression[comparison_keys[0]]
    if not _scalar(compared) or isinstance(compared, str) and len(compared) > MAX_STRING_LENGTH:
        _fail("dsl_filter_value_invalid")


def _positive_int(value: Any, *, minimum: int, maximum: int, code: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        _fail(code)


def validate_transform_profile(body: dict[str, Any]) -> None:
    _bounded_body(body)
    _exact_keys(body, _TRANSFORM_TOP_KEYS, "transform_unknown_field")
    if (
        body.get("api_version") != "agenthub/transform/v1"
        or body.get("kind") != "DocumentTransform"
    ):
        _fail("transform_version_invalid")
    spec = body.get("spec")
    if not isinstance(spec, dict):
        _fail("transform_spec_invalid")
    _exact_keys(spec, _TRANSFORM_SPEC_KEYS, "transform_spec_unknown_field")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        _fail("transform_steps_invalid")
    limits = spec.get("limits", {})
    if not isinstance(limits, dict):
        _fail("transform_limits_invalid")
    _exact_keys(limits, _LIMIT_KEYS, "transform_limits_unknown_field")
    caps = {
        "max_records": MAX_RECORDS,
        "max_output_bytes": MAX_OUTPUT_BYTES,
        "max_string_length": MAX_STRING_LENGTH,
    }
    for key, maximum in caps.items():
        if key in limits:
            _positive_int(limits[key], minimum=1, maximum=maximum, code="transform_limit_invalid")
    for step in steps:
        if not isinstance(step, dict):
            _fail("transform_step_invalid")
        op = step.get("op")
        if not isinstance(op, str):
            _fail("transform_operation_unknown")
        allowed = _STEP_KEYS.get(op)
        if allowed is None:
            _fail("transform_operation_unknown")
        _exact_keys(step, allowed, "transform_step_unknown_field")
        required = allowed - {"unicode", "whitespace", "metadata", "count", "value"}
        if not required.issubset(step):
            _fail("transform_step_missing_field")
        for key in ("pointer", "from", "to", "id", "title", "content", "metadata"):
            if key in step:
                _pointer(step[key])
        if op == "records.filter":
            _filter(step.get("where"))
        if op == "text.normalize":
            for key in ("unicode", "whitespace"):
                if key in step and not isinstance(step[key], bool):
                    _fail("transform_step_value_invalid")
        if op == "text.replace":
            for key in ("old", "new"):
                if not isinstance(step.get(key), str) or len(step[key]) > 256:
                    _fail("transform_step_value_invalid")
            _positive_int(
                step.get("count", 1), minimum=1, maximum=100, code="transform_step_value_invalid"
            )


def validate_chunking_profile(body: dict[str, Any]) -> None:
    _bounded_body(body)
    allowed = {"api_version", "kind", "strategy", "size", "overlap", "max_chunks"}
    _exact_keys(body, allowed, "chunking_unknown_field")
    if body.get("api_version") != "agenthub/chunking/v1" or body.get("kind") != "ChunkingProfile":
        _fail("chunking_version_invalid")
    if body.get("strategy") not in {"characters", "tokens", "headings", "pages", "tables"}:
        _fail("chunking_strategy_invalid")
    _positive_int(body.get("size"), minimum=100, maximum=8_000, code="chunking_size_invalid")
    overlap = body.get("overlap", 0)
    if not isinstance(overlap, int) or isinstance(overlap, bool) or not 0 <= overlap < body["size"]:
        _fail("chunking_overlap_invalid")
    _positive_int(
        body.get("max_chunks", 1_000), minimum=1, maximum=MAX_CHUNKS, code="chunking_max_invalid"
    )


def validate_retrieval_profile(body: dict[str, Any]) -> None:
    _bounded_body(body)
    allowed = {
        "api_version",
        "kind",
        "mode",
        "top_k",
        "score_threshold",
        "vector_weight",
        "keyword_weight",
        "reranker_profile_ref",
        "metadata_filter",
    }
    _exact_keys(body, allowed, "retrieval_unknown_field")
    if body.get("api_version") != "agenthub/retrieval/v1" or body.get("kind") != "RetrievalProfile":
        _fail("retrieval_version_invalid")
    mode = body.get("mode")
    if mode not in {"keyword", "vector", "hybrid"}:
        _fail("retrieval_mode_invalid")
    _positive_int(body.get("top_k"), minimum=1, maximum=50, code="retrieval_top_k_invalid")
    threshold = body.get("score_threshold", 0.0)
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        _fail("retrieval_threshold_invalid")
    if mode == "hybrid":
        vector = body.get("vector_weight")
        keyword = body.get("keyword_weight")
        if (
            not isinstance(vector, (int, float))
            or isinstance(vector, bool)
            or not math.isfinite(vector)
            or not 0 <= vector <= 1
            or not isinstance(keyword, (int, float))
            or isinstance(keyword, bool)
            or not math.isfinite(keyword)
            or not 0 <= keyword <= 1
        ):
            _fail("retrieval_weight_invalid")
        if not math.isclose(float(vector) + float(keyword), 1.0, abs_tol=1e-9):
            _fail("retrieval_weight_invalid")
    elif "vector_weight" in body or "keyword_weight" in body:
        _fail("retrieval_weight_invalid")
    reranker = body.get("reranker_profile_ref")
    if reranker is not None and (not isinstance(reranker, str) or not 1 <= len(reranker) <= 128):
        _fail("retrieval_reranker_invalid")
    if "metadata_filter" in body:
        _filter(body["metadata_filter"])


@dataclass(frozen=True)
class GovernedDocument:
    source_id: str
    title: str
    content: str
    metadata: dict[str, Any]


_MISSING = object()


def _segments(pointer: str) -> list[str]:
    _pointer(pointer)
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _get(value: Any, pointer: str, default: Any = _MISSING) -> Any:
    current = value
    for segment in _segments(pointer):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
        elif default is not _MISSING:
            return default
        else:
            _fail("dsl_pointer_missing")
    return current


def _parent(value: Any, pointer: str) -> tuple[dict[str, Any], str]:
    segments = _segments(pointer)
    current = value
    for segment in segments[:-1]:
        if not isinstance(current, dict):
            _fail("dsl_pointer_type_mismatch")
        child = current.get(segment)
        if child is None:
            child = {}
            current[segment] = child
        if not isinstance(child, dict):
            _fail("dsl_pointer_type_mismatch")
        current = child
    if not isinstance(current, dict):
        _fail("dsl_pointer_type_mismatch")
    return current, segments[-1]


def _set(value: Any, pointer: str, new_value: Any, *, only_missing: bool = False) -> None:
    parent, key = _parent(value, pointer)
    if not only_missing or key not in parent:
        parent[key] = deepcopy(new_value)


def _drop(value: Any, pointer: str) -> Any:
    parent, key = _parent(value, pointer)
    return parent.pop(key, _MISSING)


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if type(actual) is not type(expected) or not isinstance(actual, (int, float, str)):
        return False
    return {
        "gt": actual > expected,
        "gte": actual >= expected,
        "lt": actual < expected,
        "lte": actual <= expected,
    }[operator]


def _matches(record: dict[str, Any], expression: dict[str, Any]) -> bool:
    if "and" in expression:
        return all(_matches(record, item) for item in expression["and"])
    if "or" in expression:
        return any(_matches(record, item) for item in expression["or"])
    operator = next(key for key in ("eq", "ne", "gt", "gte", "lt", "lte") if key in expression)
    return _compare(_get(record, expression["field"], None), operator, expression[operator])


def _effective_limits(body: dict[str, Any]) -> dict[str, int]:
    requested = body["spec"].get("limits", {})
    return {
        "max_records": requested.get("max_records", MAX_RECORDS),
        "max_output_bytes": requested.get("max_output_bytes", MAX_OUTPUT_BYTES),
        "max_string_length": requested.get("max_string_length", MAX_STRING_LENGTH),
    }


def _enforce_runtime_budget(value: Any, limits: dict[str, int], started: float) -> None:
    if time.monotonic() - started > MAX_EXECUTION_SECONDS:
        _fail("dsl_execution_budget_exceeded")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > limits["max_output_bytes"]:
        _fail("dsl_output_too_large")
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str) and len(item) > limits["max_string_length"]:
            _fail("dsl_string_too_large")
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            if len(item) > limits["max_records"]:
                _fail("dsl_record_limit_exceeded")
            stack.extend(item)


def execute_transform(body: dict[str, Any], input_value: Any) -> list[GovernedDocument] | Any:
    """Execute a validated pipeline without dynamic code, I/O, network or shared mutation."""
    validate_transform_profile(body)
    started = time.monotonic()
    limits = _effective_limits(body)
    current = deepcopy(input_value)
    _enforce_runtime_budget(current, limits, started)
    for step in body["spec"]["steps"]:
        op = step["op"]
        if op == "records.select":
            current = deepcopy(_get(current, step["pointer"]))
            if not isinstance(current, list):
                _fail("dsl_records_expected")
        elif op == "records.filter":
            if not isinstance(current, list) or not all(isinstance(item, dict) for item in current):
                _fail("dsl_records_expected")
            current = [item for item in current if _matches(item, step["where"])]
        elif op in {
            "fields.rename",
            "fields.drop",
            "fields.default",
            "text.normalize",
            "text.replace",
        }:
            records = current if isinstance(current, list) else [current]
            if not all(isinstance(item, dict) for item in records):
                _fail("dsl_records_expected")
            for record in records:
                if op == "fields.rename":
                    found = _drop(record, step["from"])
                    if found is not _MISSING:
                        _set(record, step["to"], found)
                elif op == "fields.drop":
                    _drop(record, step["pointer"])
                elif op == "fields.default":
                    _set(record, step["pointer"], step.get("value"), only_missing=True)
                else:
                    text = _get(record, step["pointer"])
                    if not isinstance(text, str):
                        _fail("dsl_text_expected")
                    if op == "text.normalize":
                        if step.get("unicode", False):
                            text = unicodedata.normalize("NFC", text)
                        if step.get("whitespace", True):
                            text = " ".join(text.split())
                    else:
                        text = text.replace(step["old"], step["new"], step.get("count", 1))
                    _set(record, step["pointer"], text)
        elif op == "documents.map":
            records = current if isinstance(current, list) else [current]
            documents: list[GovernedDocument] = []
            for record in records:
                if not isinstance(record, dict):
                    _fail("dsl_records_expected")
                source_id = _get(record, step["id"])
                title = _get(record, step["title"])
                content = _get(record, step["content"])
                metadata = _get(record, step["metadata"], {}) if "metadata" in step else {}
                if not all(
                    isinstance(item, str) for item in (source_id, title, content)
                ) or not isinstance(metadata, dict):
                    _fail("dsl_document_invalid")
                documents.append(GovernedDocument(source_id, title, content, deepcopy(metadata)))
            current = documents
        _enforce_runtime_budget(
            [document.__dict__ for document in current]
            if isinstance(current, list) and current and isinstance(current[0], GovernedDocument)
            else current,
            limits,
            started,
        )
    return current


def chunk_with_profile(text: str, body: dict[str, Any]) -> list[str]:
    """Deterministically chunk text under a validated immutable profile."""
    validate_chunking_profile(body)
    if not isinstance(text, str) or len(text) > MAX_OUTPUT_BYTES:
        _fail("chunking_input_invalid")
    strategy = body["strategy"]
    if strategy == "characters":
        units = list(text)
        separator = ""
    elif strategy == "tokens":
        units = text.split()
        separator = " "
    elif strategy == "headings":
        units = text.splitlines()
        separator = "\n"
    elif strategy == "pages":
        units = text.split("\f")
        separator = "\f"
    else:
        units = text.split("\n\n")
        separator = "\n\n"
    size, overlap = body["size"], body.get("overlap", 0)
    chunks: list[str] = []
    start = 0
    while start < len(units):
        chunk = separator.join(units[start : start + size]).strip()
        if chunk:
            chunks.append(chunk)
        if len(chunks) > body.get("max_chunks", 1_000):
            _fail("chunking_max_exceeded")
        start += size - overlap
    return chunks


def normalize_retrieval_profile(body: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded provider projection; authority fields can never enter it."""
    validate_retrieval_profile(body)
    return {
        key: deepcopy(value) for key, value in body.items() if key not in {"api_version", "kind"}
    }
