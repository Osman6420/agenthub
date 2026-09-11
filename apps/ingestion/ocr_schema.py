from __future__ import annotations

import re
from typing import Any

from apps.tools.tool_schema import ToolArtifactError, _validate_public_hostname

_LOGICAL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SECRET_REF = re.compile(r"^secret:[A-Za-z0-9._-]{1,128}$")


class OcrProfileValidationError(ValueError):
    pass


def validate_ocr_profile_fields(**fields: Any) -> None:
    logical_id = fields.get("logical_id")
    if not isinstance(logical_id, str) or not _LOGICAL_ID.fullmatch(logical_id):
        raise OcrProfileValidationError("OCR_PROFILE_LOGICAL_ID_INVALID")
    revision = fields.get("revision")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or not 1 <= revision <= 1_000_000
    ):
        raise OcrProfileValidationError("OCR_PROFILE_REVISION_INVALID")
    if fields.get("provider") != "async_markdown_ocr" or fields.get("scheme") != "https":
        raise OcrProfileValidationError("OCR_PROFILE_PROVIDER_INVALID")
    try:
        _validate_public_hostname(fields.get("host"))
    except ToolArtifactError as exc:
        raise OcrProfileValidationError("OCR_PROFILE_HOST_INVALID") from exc
    port = fields.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise OcrProfileValidationError("OCR_PROFILE_PORT_INVALID")
    base_path = fields.get("base_path")
    if (
        not isinstance(base_path, str)
        or not base_path.startswith("/")
        or base_path.endswith("/")
        or len(base_path) > 512
        or "?" in base_path
        or "#" in base_path
    ):
        raise OcrProfileValidationError("OCR_PROFILE_PATH_INVALID")
    secret_ref = fields.get("secret_ref")
    if not isinstance(secret_ref, str) or not _SECRET_REF.fullmatch(secret_ref):
        raise OcrProfileValidationError("OCR_PROFILE_SECRET_REF_INVALID")
    _bounded_int(fields, "timeout_seconds", 1, 120)
    _bounded_int(fields, "poll_interval_seconds", 2, 5)
    _bounded_int(fields, "max_poll_attempts", 1, 1800)
    _bounded_int(fields, "max_upload_bytes", 1_024, 52_428_800)
    _bounded_int(fields, "max_pages", 1, 500)
    _bounded_int(fields, "max_result_bytes", 1_024, 25_000_000)


def _bounded_int(fields: dict[str, Any], name: str, minimum: int, maximum: int) -> None:
    value = fields.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise OcrProfileValidationError(f"OCR_PROFILE_{name.upper()}_INVALID")
