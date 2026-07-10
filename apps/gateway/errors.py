"""Standard error envelope and stable error codes (v3 plan §11.4).

All gateway failures return the same JSON shape with a stable ``code``. Messages are
safe for clients; diagnosable internal detail is logged, never returned.
"""

from __future__ import annotations

import logging
from typing import Any

from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class ErrorCode:
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    CONSUMER_DISABLED = "CONSUMER_DISABLED"
    SCENARIO_NOT_ALLOWED = "SCENARIO_NOT_ALLOWED"
    CAPABILITY_DENIED = "CAPABILITY_DENIED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    INPUT_CONTRACT_VIOLATION = "INPUT_CONTRACT_VIOLATION"
    EXECUTION_CONTEXT_INVALID = "EXECUTION_CONTEXT_INVALID"
    RELEASE_NOT_AVAILABLE = "RELEASE_NOT_AVAILABLE"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    RUNTIME_NOT_AVAILABLE = "RUNTIME_NOT_AVAILABLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Stable set for contract snapshot tests.
ERROR_CODES: frozenset[str] = frozenset(
    v for k, v in vars(ErrorCode).items() if not k.startswith("_") and isinstance(v, str)
)


class ApiError(Exception):
    """Raised inside gateway views to produce a standard error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status_code: int,
        retryable: bool = False,
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status_code = http_status_code
        self.retryable = retryable
        self.details = details or []


def error_body(
    code: str, message: str, request_id: str, retryable: bool, details: list[Any]
) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "retryable": retryable,
            "details": details,
        }
    }


def error_response(error: ApiError, request_id: str) -> Response:
    return Response(
        error_body(error.code, error.message, request_id, error.retryable, error.details),
        status=error.http_status_code,
    )


def exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF exception handler mapping ApiError and framework errors to the envelope."""
    request = context.get("request")
    request_id = getattr(request, "request_id", "") if request is not None else ""

    if isinstance(exc, ApiError):
        return error_response(exc, request_id)

    # Let DRF classify auth/throttle/validation, then normalize the body.
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("unhandled gateway error")
        return Response(
            error_body(
                ErrorCode.INTERNAL_ERROR,
                "The request cannot be completed.",
                request_id,
                False,
                [],
            ),
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = _classify(response.status_code)
    message = _safe_message(response.status_code)
    retryable = response.status_code in (429, 503)
    return Response(
        error_body(code, message, request_id, retryable, []),
        status=response.status_code,
        headers={k: v for k, v in response.headers.items() if k.lower() == "retry-after"},
    )


def _classify(status_code: int) -> str:
    return {
        401: ErrorCode.AUTHENTICATION_REQUIRED,
        403: ErrorCode.CAPABILITY_DENIED,
        429: ErrorCode.RATE_LIMITED,
        400: ErrorCode.VALIDATION_ERROR,
    }.get(status_code, ErrorCode.INTERNAL_ERROR)


def _safe_message(status_code: int) -> str:
    return {
        401: "Authentication is required.",
        403: "The request is not permitted.",
        429: "Too many requests.",
        400: "The request is invalid.",
    }.get(status_code, "The request cannot be completed.")
