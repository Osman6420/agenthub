from __future__ import annotations

import re
import uuid
from typing import Any

from apps.tools.tool_schema import ToolArtifactError, _validate_public_hostname

_LOGICAL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SECRET_REF = re.compile(r"^secret:[A-Za-z0-9._-]{1,128}$")
_ALLOWED_ARTIFACT_FIELDS = frozenset({"profile_id"})


class ModelProfileValidationError(ValueError):
    pass


def validate_model_profile_artifact(body: dict[str, Any]) -> None:
    if set(body) != _ALLOWED_ARTIFACT_FIELDS:
        raise ModelProfileValidationError("model_profile must contain only profile_id")
    try:
        uuid.UUID(str(body["profile_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ModelProfileValidationError("model_profile.profile_id must be a UUID") from exc


def validate_profile_fields(
    *,
    logical_id: str,
    revision: int,
    provider: str,
    scheme: str,
    host: str,
    port: int,
    path: str,
    model: str,
    secret_ref: str,
    timeout_seconds: int,
    max_response_bytes: int,
    max_output_tokens: int,
) -> None:
    if not _LOGICAL_ID.fullmatch(logical_id):
        raise ModelProfileValidationError("MODEL_PROFILE_LOGICAL_ID_INVALID")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or not 1 <= revision <= 1_000_000
    ):
        raise ModelProfileValidationError("MODEL_PROFILE_REVISION_INVALID")
    if provider != "openai_compatible" or scheme != "https":
        raise ModelProfileValidationError("MODEL_PROFILE_PROVIDER_INVALID")
    try:
        _validate_public_hostname(host)
    except ToolArtifactError as exc:
        raise ModelProfileValidationError("MODEL_PROFILE_HOST_INVALID") from exc
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ModelProfileValidationError("MODEL_PROFILE_PORT_INVALID")
    if not path.startswith("/") or len(path) > 512 or "?" in path or "#" in path:
        raise ModelProfileValidationError("MODEL_PROFILE_PATH_INVALID")
    if not model or len(model) > 200 or any(c in model for c in "\r\n"):
        raise ModelProfileValidationError("MODEL_PROFILE_MODEL_INVALID")
    if not _SECRET_REF.fullmatch(secret_ref):
        raise ModelProfileValidationError("MODEL_PROFILE_SECRET_REF_INVALID")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= 120
    ):
        raise ModelProfileValidationError("MODEL_PROFILE_TIMEOUT_INVALID")
    if (
        isinstance(max_response_bytes, bool)
        or not isinstance(max_response_bytes, int)
        or not 1_024 <= max_response_bytes <= 10_000_000
    ):
        raise ModelProfileValidationError("MODEL_PROFILE_RESPONSE_LIMIT_INVALID")
    if (
        isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or not 1 <= max_output_tokens <= 32_768
    ):
        raise ModelProfileValidationError("MODEL_PROFILE_TOKEN_LIMIT_INVALID")
