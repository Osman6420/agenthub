"""Transport adapters for the tool execution proxy.

An adapter turns a policy-approved, egress-validated request into a bounded response.
The default ``DeterministicToolAdapter`` performs **no network I/O**: it proves the
policy/egress/secret seam end to end without opening a socket, mirroring the
deterministic model/retrieval providers used elsewhere until a reviewed real client is
introduced. A production HTTP/MCP adapter (with TLS verification, disabled redirects,
and a bounded read) plugs in behind this same protocol and requires explicit approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apps.tools.egress import ValidatedDestination

MAX_ECHO_ITEMS = 20


class ToolAdapterError(RuntimeError):
    """Raised when the transport cannot produce a usable, bounded response."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ToolAdapterUncertain(RuntimeError):
    """Raised when a request was dispatched but its outcome cannot be confirmed.

    A timeout or lost connection *after* the request left the proxy means the side
    effect may or may not have happened. The caller must record this as an uncertain
    outcome and must never blindly retry (v3 plan §17 approved decisions).
    """

    def __init__(self, code: str = "OUTCOME_UNKNOWN") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ToolAdapterRequest:
    protocol: str
    method: str | None
    destination: ValidatedDestination
    payload: dict[str, Any]
    credential: str | None
    timeout_seconds: int
    max_response_bytes: int


@dataclass(frozen=True)
class ToolAdapterResponse:
    status_code: int
    body: dict[str, Any]


class ToolAdapter(Protocol):
    def call(self, request: ToolAdapterRequest) -> ToolAdapterResponse: ...


class DeterministicToolAdapter:
    """No-egress default. Returns a deterministic, bounded acknowledgement so the
    surrounding governance (contracts, field allowlists, secret resolution) can be
    exercised without a real outbound call."""

    # No socket is opened, so DNS/egress validation is not required (and is skipped
    # unless a resolver is explicitly injected, keeping offline runs deterministic).
    requires_egress = False

    def call(self, request: ToolAdapterRequest) -> ToolAdapterResponse:
        echo = {
            key: request.payload[key]
            for key in sorted(request.payload)[:MAX_ECHO_ITEMS]
            if isinstance(request.payload[key], (str, int, float, bool))
        }
        return ToolAdapterResponse(status_code=200, body={"status": "ok", "echo": echo})


class RealEgressAdapter:
    """Dispatch to the real HTTPS or MCP transport by the request protocol."""

    def __init__(self) -> None:
        from apps.tools.http_adapter import HttpToolAdapter
        from apps.tools.mcp_adapter import McpToolAdapter

        self._http = HttpToolAdapter()
        self._mcp = McpToolAdapter()

    def call(self, request: ToolAdapterRequest) -> ToolAdapterResponse:
        if request.protocol == "mcp":
            return self._mcp.call(request)
        return self._http.call(request)


def get_configured_adapter() -> ToolAdapter:
    """Return the adapter selected by ``settings.TOOL_ADAPTER`` (default: no egress).

    ``"http"`` (or ``"real"``) opts into real egress and dispatches by protocol to the
    HTTPS/MCP transports; every other value (and the default) keeps the deterministic
    no-egress adapter, so tests and unconfigured environments never make an outbound call.
    """
    from django.conf import settings

    if getattr(settings, "TOOL_ADAPTER", "deterministic") in {"http", "real"}:
        return RealEgressAdapter()
    return DeterministicToolAdapter()
