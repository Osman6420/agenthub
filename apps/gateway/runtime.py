"""Runtime facade: verify the ExecutionContext, then delegate to the RAG runtime.

The gateway (transport) maps domain/runtime exceptions to the standard error
envelope. The orchestration layer never imports the gateway.
"""

from __future__ import annotations

from typing import Any

from apps.gateway.errors import ApiError, ErrorCode
from apps.gateway.execution_context import ExecutionContextInvalid, verify_execution_context
from apps.orchestration.providers import ModelProviderError
from apps.orchestration.runtime import RetrievalError, RuntimeReleaseError, run_rag


def dispatch(
    *,
    execution_context: dict[str, Any],
    validated_input: dict[str, Any],
    operation: str,
    release: Any,
) -> dict[str, Any]:
    """Verify context and run the RAG runtime. Returns a result dict for the view."""
    try:
        verify_execution_context(execution_context)
    except ExecutionContextInvalid as exc:
        raise ApiError(
            ErrorCode.EXECUTION_CONTEXT_INVALID,
            "The execution context is invalid.",
            http_status_code=500,
        ) from exc

    try:
        result = run_rag(
            execution_context=execution_context,
            validated_input=validated_input,
            release=release,
        )
    except RuntimeReleaseError as exc:
        raise ApiError(
            ErrorCode.RELEASE_NOT_AVAILABLE,
            "No active release for this scenario.",
            http_status_code=503,
            retryable=True,
        ) from exc
    except RetrievalError as exc:
        raise ApiError(
            ErrorCode.RETRIEVAL_FAILED,
            "Retrieval failed.",
            http_status_code=502,
            retryable=True,
        ) from exc
    except ModelProviderError as exc:
        raise ApiError(
            ErrorCode.MODEL_PROVIDER_FAILED,
            "The model provider failed.",
            http_status_code=502,
            retryable=True,
        ) from exc

    return {
        "status": result.status,
        "output": result.output,
        "usage": result.usage,
        "fallback_used": result.fallback_used,
    }
