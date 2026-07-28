"""Bounded inbound OpenAI-compatible request and response adaptation.

This module is transport shaping only. ``model`` is an AgentHub scenario alias,
never a provider model id or authorization claim. Runtime policy, release routing,
contracts and tools remain owned by the gateway/runtime layers.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, NoReturn

import jsonschema

from apps.gateway.errors import ApiError, ErrorCode
from apps.releases.services import get_artifact_body_for_role

MAX_MESSAGES = 64
MAX_MESSAGE_CHARS = 32_000
MAX_TOTAL_CHARS = 100_000
MAX_USER_CHARS = 256
ALLOWED_ROLES = frozenset({"developer", "system", "user", "assistant"})


def parse_chat_request(data: Any) -> tuple[str, dict[str, Any]]:
    body = _mapping(data)
    _only(body, {"model", "messages", "stream", "user"})
    alias = _model(body)
    _stream_false(body)
    user = _optional_user(body)
    messages = _messages(body.get("messages"), param="messages")
    payload: dict[str, Any] = {
        "query": _latest_user(messages),
        "__openai_messages": messages,
    }
    if user is not None:
        payload["__openai_user"] = user
    return alias, payload


def parse_responses_request(data: Any) -> tuple[str, dict[str, Any]]:
    body = _mapping(data)
    _only(body, {"model", "input", "background", "stream", "user"})
    alias = _model(body)
    _stream_false(body)
    user = _optional_user(body)
    background = body.get("background", False)
    if not isinstance(background, bool):
        _invalid("background must be a boolean.", "background")
    raw_input = body.get("input")
    if isinstance(raw_input, str):
        messages = _messages([{"role": "user", "content": raw_input}], param="input")
    else:
        messages = _messages(raw_input, param="input")
    payload: dict[str, Any] = {
        "query": _latest_user(messages),
        "__openai_messages": messages,
        "__openai_background": background,
    }
    if user is not None:
        payload["__openai_user"] = user
    return alias, payload


def prepare_runtime_input(release: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Include normalized history only when the pinned input schema accepts it."""
    query_only = {"query": payload["query"]}
    with_history = {"query": payload["query"], "messages": payload["__openai_messages"]}
    schema = get_artifact_body_for_role(release, "input_contract")
    if schema is None:
        return with_history
    try:
        jsonschema.validate(with_history, schema)
    except jsonschema.ValidationError:
        return query_only
    return with_history


def chat_response(body: dict[str, Any], alias: str) -> dict[str, Any]:
    output = body.get("output")
    return {
        "id": _opaque("chatcmpl", str(body.get("request_id", ""))),
        "object": "chat.completion",
        "created": _created(),
        "model": alias,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _output_text(output)},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(body.get("usage")),
    }


def responses_response(body: dict[str, Any], alias: str) -> dict[str, Any]:
    request_id = str(body.get("request_id", ""))
    response_id = str(body.get("response_id") or _opaque("resp", request_id))
    if int(body.get("_http_status", 200)) == 202:
        return {
            "id": response_id,
            "object": "response",
            "created_at": _created(),
            "status": "queued",
            "model": alias,
            "background": True,
            "output": [],
            "metadata": {"run_id": str(body["run_id"])},
        }
    text = _output_text(body.get("output"))
    return {
        "id": response_id,
        "object": "response",
        "created_at": _created(),
        "status": "completed",
        "model": alias,
        "background": False,
        "output": [
            {
                "id": _opaque("msg", request_id),
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": _responses_usage(body.get("usage")),
    }


def compatible_error(body: Any) -> dict[str, Any]:
    error = body.get("error", {}) if isinstance(body, dict) else {}
    code = str(error.get("code", ErrorCode.INTERNAL_ERROR))
    details = error.get("details", [])
    param = None
    if isinstance(details, list) and details and isinstance(details[0], dict):
        path = details[0].get("path")
        if isinstance(path, list) and path:
            param = ".".join(str(part) for part in path)
    return {
        "error": {
            "message": str(error.get("message", "The request cannot be completed.")),
            "type": _error_type(code),
            "param": param,
            "code": code,
        }
    }


def _mapping(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        _invalid("Request body must be a JSON object.", None)
    return data


def _only(body: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        _invalid("Unsupported request field.", unknown[0])


def _model(body: dict[str, Any]) -> str:
    value = body.get("model")
    if not isinstance(value, str) or not value or len(value) > 128:
        _invalid("model must be a bounded scenario alias.", "model")
    return value


def _stream_false(body: dict[str, Any]) -> None:
    if body.get("stream", False) is not False:
        _invalid("Streaming is not supported.", "stream")


def _optional_user(body: dict[str, Any]) -> str | None:
    if "user" not in body:
        return None
    value = body["user"]
    if not isinstance(value, str) or not value or len(value) > MAX_USER_CHARS:
        _invalid("user must be a bounded non-empty string.", "user")
    return value


def _messages(value: Any, *, param: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value or len(value) > MAX_MESSAGES:
        _invalid(f"{param} must contain between 1 and {MAX_MESSAGES} messages.", param)
    normalized: list[dict[str, str]] = []
    total = 0
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            _invalid("Each message must contain only role and text content.", f"{param}.{index}")
        role = item.get("role")
        content = item.get("content")
        if role not in ALLOWED_ROLES:
            _invalid("Unsupported message role.", f"{param}.{index}.role")
        if not isinstance(content, str) or not content or len(content) > MAX_MESSAGE_CHARS:
            _invalid("Message content must be bounded non-empty text.", f"{param}.{index}.content")
        if any(ord(character) < 32 and character not in "\n\r\t" for character in content):
            _invalid(
                "Message content contains unsupported control characters.",
                f"{param}.{index}.content",
            )
        total += len(content)
        if total > MAX_TOTAL_CHARS:
            _invalid("Message history exceeds the total text limit.", param)
        normalized.append({"role": str(role), "content": content})
    return normalized


def _latest_user(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message["role"] == "user":
            return message["content"]
    _invalid("At least one user message is required.", "messages")


def _invalid(message: str, param: str | None) -> NoReturn:
    details = [{"path": param.split(".")}] if param else []
    raise ApiError(ErrorCode.VALIDATION_ERROR, message, http_status_code=400, details=details)


def _opaque(prefix: str, request_id: str) -> str:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _created() -> int:
    import time

    return int(time.time())


def _output_text(output: Any) -> str:
    if isinstance(output, dict) and isinstance(output.get("answer"), str):
        return output["answer"]
    return json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _usage(value: Any) -> dict[str, int]:
    usage = value if isinstance(value, dict) else {}
    prompt = int(usage.get("input_tokens", 0))
    completion = int(usage.get("output_tokens", 0))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _responses_usage(value: Any) -> dict[str, int]:
    usage = value if isinstance(value, dict) else {}
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _error_type(code: str) -> str:
    if code == ErrorCode.AUTHENTICATION_REQUIRED:
        return "authentication_error"
    if code in {ErrorCode.CAPABILITY_DENIED, ErrorCode.SCENARIO_NOT_ALLOWED}:
        return "permission_error"
    if code == ErrorCode.RATE_LIMITED:
        return "rate_limit_error"
    if code in {
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.INPUT_CONTRACT_VIOLATION,
        ErrorCode.IDEMPOTENCY_CONFLICT,
    }:
        return "invalid_request_error"
    return "api_error"
