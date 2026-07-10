"""Runtime facade seam.

The gateway resolves and authorizes a request, then hands a verified
ExecutionContext and validated input to the runtime. The RAG runtime is Sprint 4;
until then this facade returns an ``accepted`` result so the full gateway path is
exercised without fabricating model output.
"""

from __future__ import annotations

from typing import Any

from apps.gateway.execution_context import verify_execution_context


def dispatch(
    *, execution_context: dict[str, Any], validated_input: dict[str, Any], operation: str
) -> dict[str, Any]:
    """Verify the context and dispatch to the runtime. Returns a result dict.

    Sprint 3 stub: no generation. Returns ``status='accepted'`` after verifying the
    ExecutionContext, so callers and tests exercise the real authorization path.
    """
    verify_execution_context(execution_context)
    return {
        "status": "accepted",
        "output": None,
        "detail": "ExecutionContext issued; runtime generation is not yet available.",
    }
