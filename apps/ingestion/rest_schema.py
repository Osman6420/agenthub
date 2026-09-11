"""Closed validation/interpreter for tenant-authored generic REST pull contracts.

The contract maps bounded JSON data only.  It cannot select a destination, add headers, execute
expressions, or follow response-provided URLs.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_MAPPING_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_PATH_INPUT = re.compile(r"^\{input:([A-Za-z][A-Za-z0-9_]{0,63})\}$")
_FORBIDDEN_TEXT = ("http://", "https://", "{{", "}}", "${", "javascript:")
_MAX_TREE_DEPTH = 8
_MAX_TREE_NODES = 500


class RestContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_contract_json(definition: dict[str, Any]) -> str:
    return json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate_contract(definition: object) -> dict[str, Any]:
    if not isinstance(definition, dict):
        raise RestContractError("REST_CONTRACT_NOT_OBJECT")
    _exact_keys(definition, {"version", "inputs", "request", "response", "pagination"})
    if definition.get("version") != 1:
        raise RestContractError("REST_CONTRACT_VERSION_UNSUPPORTED")
    inputs = definition.get("inputs")
    if not isinstance(inputs, dict) or len(inputs) > 50:
        raise RestContractError("REST_INPUT_SCHEMA_INVALID")
    for name, spec in inputs.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name) or not isinstance(spec, dict):
            raise RestContractError("REST_INPUT_SCHEMA_INVALID")
        kind = spec.get("type")
        if kind == "string":
            _exact_keys(spec, {"type", "max_length"})
            _bounded_int(spec.get("max_length"), 1, 1024, "REST_INPUT_SCHEMA_INVALID")
        elif kind == "integer":
            _exact_keys(spec, {"type", "minimum", "maximum"})
            minimum, maximum = spec.get("minimum"), spec.get("maximum")
            if (
                isinstance(minimum, bool)
                or isinstance(maximum, bool)
                or not isinstance(minimum, int)
                or not isinstance(maximum, int)
                or minimum > maximum
            ):
                raise RestContractError("REST_INPUT_SCHEMA_INVALID")
        elif kind == "boolean":
            _exact_keys(spec, {"type"})
        elif kind == "enum":
            _exact_keys(spec, {"type", "values"})
            values = spec.get("values")
            if (
                not isinstance(values, list)
                or not 1 <= len(values) <= 100
                or any(not isinstance(v, str) or not v or len(v) > 256 for v in values)
                or len(set(values)) != len(values)
            ):
                raise RestContractError("REST_INPUT_SCHEMA_INVALID")
        else:
            raise RestContractError("REST_INPUT_SCHEMA_INVALID")

    request = definition.get("request")
    if not isinstance(request, dict):
        raise RestContractError("REST_REQUEST_INVALID")
    _exact_keys(request, {"method", "path", "query", "body"}, optional={"query", "body"})
    if request.get("method") not in {"GET", "POST"}:
        raise RestContractError("REST_METHOD_INVALID")
    _validate_relative_path(request.get("path"), allowed_placeholders=set(inputs), detail=False)
    _validate_tree(request.get("query", {}), allowed_inputs=set(inputs), allow_pagination=True)
    if "body" in request:
        _validate_tree(request["body"], allowed_inputs=set(inputs), allow_pagination=True)
    if request.get("method") == "GET" and "body" in request:
        raise RestContractError("REST_GET_BODY_FORBIDDEN")

    response = definition.get("response")
    if not isinstance(response, dict):
        raise RestContractError("REST_RESPONSE_MAPPING_INVALID")
    _exact_keys(
        response,
        {
            "items_pointer",
            "id_pointer",
            "revision_pointer",
            "title_pointer",
            "deleted_pointer",
            "content_pointer",
            "content_encoding",
            "mime_type",
            "detail",
        },
        optional={
            "revision_pointer",
            "title_pointer",
            "deleted_pointer",
            "content_pointer",
            "detail",
        },
    )
    for name in (
        "items_pointer",
        "id_pointer",
        "revision_pointer",
        "title_pointer",
        "deleted_pointer",
        "content_pointer",
    ):
        if name in response:
            _validate_pointer(response[name])
    if response.get("content_encoding") not in {"utf8_text", "base64"}:
        raise RestContractError("REST_CONTENT_ENCODING_INVALID")
    mime_type = response.get("mime_type")
    if not isinstance(mime_type, str) or not mime_type or len(mime_type) > 128:
        raise RestContractError("REST_MIME_TYPE_INVALID")
    detail = response.get("detail")
    if detail is None:
        if "content_pointer" not in response:
            raise RestContractError("REST_CONTENT_POINTER_REQUIRED")
    else:
        if "content_pointer" in response or not isinstance(detail, dict):
            raise RestContractError("REST_DETAIL_INVALID")
        _exact_keys(detail, {"path", "content_pointer"})
        _validate_relative_path(detail.get("path"), allowed_placeholders={"id"}, detail=True)
        _validate_pointer(detail.get("content_pointer"))

    pagination = definition.get("pagination")
    if not isinstance(pagination, dict):
        raise RestContractError("REST_PAGINATION_INVALID")
    mode = pagination.get("mode")
    if mode == "none":
        _exact_keys(pagination, {"mode"})
    elif mode in {"page_number", "offset"}:
        _exact_keys(pagination, {"mode", "parameter", "page_size"})
        _validate_parameter_name(pagination.get("parameter"))
        _bounded_int(pagination.get("page_size"), 1, 1000, "REST_PAGINATION_INVALID")
    elif mode == "cursor":
        _exact_keys(pagination, {"mode", "parameter", "page_size", "cursor_pointer"})
        _validate_parameter_name(pagination.get("parameter"))
        _bounded_int(pagination.get("page_size"), 1, 1000, "REST_PAGINATION_INVALID")
        _validate_pointer(pagination.get("cursor_pointer"))
    else:
        raise RestContractError("REST_PAGINATION_INVALID")
    return definition


def validate_source_inputs(definition: dict[str, Any], values: object) -> dict[str, Any]:
    validate_contract(definition)
    specs = definition["inputs"]
    if not isinstance(values, dict) or set(values) != set(specs):
        raise RestContractError("REST_SOURCE_INPUTS_INVALID")
    normalized: dict[str, Any] = {}
    for name, spec in specs.items():
        value = values[name]
        kind = spec["type"]
        if kind == "string":
            if not isinstance(value, str) or len(value) > spec["max_length"]:
                raise RestContractError("REST_SOURCE_INPUTS_INVALID")
        elif kind == "integer":
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not spec["minimum"] <= value <= spec["maximum"]
            ):
                raise RestContractError("REST_SOURCE_INPUTS_INVALID")
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise RestContractError("REST_SOURCE_INPUTS_INVALID")
        elif kind == "enum" and value not in spec["values"]:
            raise RestContractError("REST_SOURCE_INPUTS_INVALID")
        if isinstance(value, str) and any(token in value.lower() for token in _FORBIDDEN_TEXT):
            raise RestContractError("REST_SOURCE_INPUTS_FORBIDDEN_VALUE")
        normalized[name] = value
    return normalized


def render_path(template: str, inputs: dict[str, Any], *, detail_id: str | None = None) -> str:
    rendered: list[str] = []
    for segment in template.split("/"):
        match = _PATH_INPUT.fullmatch(segment)
        if match:
            name = match.group(1)
            value = detail_id if name == "id" and detail_id is not None else inputs.get(name)
            if value is None:
                raise RestContractError("REST_PATH_INPUT_MISSING")
            rendered.append(quote(str(value), safe=""))
        else:
            rendered.append(segment)
    return "/".join(rendered)


def render_tree(
    value: Any,
    inputs: dict[str, Any],
    *,
    page_number: int = 1,
    offset: int = 0,
    page_size: int = 0,
    cursor: str = "",
) -> Any:
    if isinstance(value, dict):
        if len(value) == 1 and "$input" in value:
            return inputs[value["$input"]]
        if len(value) == 1 and "$page_number" in value:
            return page_number
        if len(value) == 1 and "$offset" in value:
            return offset
        if len(value) == 1 and "$page_size" in value:
            return page_size
        if len(value) == 1 and "$cursor" in value:
            return cursor
        return {
            key: render_tree(
                item,
                inputs,
                page_number=page_number,
                offset=offset,
                page_size=page_size,
                cursor=cursor,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            render_tree(
                item,
                inputs,
                page_number=page_number,
                offset=offset,
                page_size=page_size,
                cursor=cursor,
            )
            for item in value
        ]
    return value


def resolve_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise RestContractError("REST_POINTER_NOT_FOUND")
    return current


def _validate_tree(value: Any, *, allowed_inputs: set[str], allow_pagination: bool) -> None:
    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_TREE_NODES or depth > _MAX_TREE_DEPTH:
            raise RestContractError("REST_MAPPING_TOO_COMPLEX")
        if (
            item is None
            or isinstance(item, bool)
            or isinstance(item, int)
            or isinstance(item, float)
        ):
            return
        if isinstance(item, str):
            if len(item) > 4096 or any(token in item.lower() for token in _FORBIDDEN_TEXT):
                raise RestContractError("REST_MAPPING_STRING_FORBIDDEN")
            return
        if isinstance(item, list):
            if len(item) > 100:
                raise RestContractError("REST_MAPPING_TOO_COMPLEX")
            for child in item:
                visit(child, depth + 1)
            return
        if not isinstance(item, dict) or len(item) > 100:
            raise RestContractError("REST_MAPPING_VALUE_INVALID")
        if len(item) == 1 and "$input" in item:
            if item["$input"] not in allowed_inputs:
                raise RestContractError("REST_INPUT_REFERENCE_INVALID")
            return
        pagination_keys = {"$page_number", "$offset", "$page_size", "$cursor"}
        if len(item) == 1 and set(item) <= pagination_keys:
            if not allow_pagination or item[next(iter(item))] is not True:
                raise RestContractError("REST_PAGINATION_REFERENCE_INVALID")
            return
        if any(str(key).startswith("$") for key in item):
            raise RestContractError("REST_PLACEHOLDER_INVALID")
        for key, child in item.items():
            if not isinstance(key, str) or not _MAPPING_KEY.fullmatch(key):
                raise RestContractError("REST_MAPPING_KEY_INVALID")
            visit(child, depth + 1)

    visit(value, 0)


def _validate_relative_path(value: object, *, allowed_placeholders: set[str], detail: bool) -> None:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 512:
        raise RestContractError("REST_PATH_INVALID")
    if "\\" in value or "%" in value or "?" in value or "#" in value or "//" in value:
        raise RestContractError("REST_PATH_INVALID")
    segments = value.split("/")[1:]
    if any(segment in {"", ".", ".."} for segment in segments):
        raise RestContractError("REST_PATH_INVALID")
    placeholders: list[str] = []
    for segment in segments:
        if "{" in segment or "}" in segment:
            match = _PATH_INPUT.fullmatch(segment)
            if not match or match.group(1) not in allowed_placeholders:
                raise RestContractError("REST_PATH_PLACEHOLDER_INVALID")
            placeholders.append(match.group(1))
    if detail and placeholders != ["id"]:
        raise RestContractError("REST_DETAIL_PATH_ID_REQUIRED")


def _validate_pointer(value: object) -> None:
    if not isinstance(value, str) or len(value) > 512 or (value and not value.startswith("/")):
        raise RestContractError("REST_POINTER_INVALID")
    if "~" in value and re.search(r"~(?![01])", value):
        raise RestContractError("REST_POINTER_INVALID")


def _validate_parameter_name(value: object) -> None:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise RestContractError("REST_PAGINATION_INVALID")


def _exact_keys(
    value: dict[str, Any], allowed: set[str], *, optional: set[str] | None = None
) -> None:
    optional = optional or set()
    unknown = set(value) - allowed
    required = allowed - optional
    if unknown or not required <= set(value):
        raise RestContractError("REST_CONTRACT_UNKNOWN_OR_MISSING_FIELD")


def _bounded_int(value: object, minimum: int, maximum: int, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RestContractError(code)
