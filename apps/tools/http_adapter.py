"""Real HTTPS tool adapter (stdlib only), enabled by configuration.

SSRF-safe by construction: it connects to the *already-validated public IP* from the
egress check while verifying the TLS certificate and sending SNI/Host for the original
hostname, which closes the DNS-rebinding TOCTOU window. Redirects are never followed,
the response body is read under a hard byte cap, and a timeout after dispatch is
surfaced as an uncertain outcome (never a false success). Only ``https`` reaches here.

The connection factory is injectable so tests exercise request-building and
response-handling fully offline; real sockets are only opened in the default factory.
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
from collections.abc import Callable
from typing import Any, Protocol

from apps.tools.adapters import (
    ToolAdapterError,
    ToolAdapterRequest,
    ToolAdapterResponse,
    ToolAdapterUncertain,
)


class _HttpResponse(Protocol):
    status: int

    def read(self, amount: int) -> bytes: ...


class _HttpConnection(Protocol):
    def request(
        self, method: str, url: str, body: bytes | None = ..., headers: dict[str, str] = ...
    ) -> None: ...

    def getresponse(self) -> _HttpResponse: ...

    def close(self) -> None: ...


# (ip, port, timeout_seconds, server_hostname) -> connection
ConnectionFactory = Callable[[str, int, float, str], _HttpConnection]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Dials a fixed IP while verifying the certificate for the original hostname."""

    def __init__(
        self, ip: str, port: int, *, server_hostname: str, timeout: float, context: ssl.SSLContext
    ) -> None:
        super().__init__(server_hostname, port, timeout=timeout, context=context)
        self._pinned_ip = ip
        self._ssl_context = context

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        # ``self.host`` is the original hostname → SNI + cert hostname verification.
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


def _default_connection_factory(
    ip: str, port: int, timeout: float, server_hostname: str
) -> _HttpConnection:
    context = ssl.create_default_context()
    return _PinnedHTTPSConnection(
        ip, port, server_hostname=server_hostname, timeout=timeout, context=context
    )


class HttpToolAdapter:
    """Bounded, redirect-free HTTPS adapter used when tool egress is enabled."""

    def __init__(self, *, connection_factory: ConnectionFactory | None = None) -> None:
        self._factory = connection_factory or _default_connection_factory

    def call(self, request: ToolAdapterRequest) -> ToolAdapterResponse:
        if request.protocol != "http":
            # MCP egress uses a separate adapter; this one speaks plain HTTPS.
            raise ToolAdapterError("PROTOCOL_UNSUPPORTED")
        destination = request.destination
        if not destination.ip_addresses:
            raise ToolAdapterError("DESTINATION_UNRESOLVED")
        ip = destination.ip_addresses[0]
        method = request.method or "POST"
        path = destination.path_prefix or "/"
        headers = {
            "Host": destination.host,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if request.credential:
            headers["Authorization"] = f"Bearer {request.credential}"
        body = json.dumps(request.payload, separators=(",", ":")).encode("utf-8")

        connection = self._factory(
            ip, destination.port, float(request.timeout_seconds), destination.host
        )
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            status = int(response.status)
            raw = response.read(request.max_response_bytes + 1)
        except TimeoutError as exc:
            # Dispatched, but the outcome cannot be confirmed: never a false success.
            raise ToolAdapterUncertain() from exc
        except OSError as exc:
            raise ToolAdapterError("CONNECTION_FAILED") from exc
        finally:
            _safe_close(connection)

        if 300 <= status < 400:
            raise ToolAdapterError("REDIRECT_NOT_ALLOWED")
        if len(raw) > request.max_response_bytes:
            raise ToolAdapterError("RESPONSE_TOO_LARGE")
        if not 200 <= status < 300:
            raise ToolAdapterError("UPSTREAM_STATUS")
        try:
            parsed: Any = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ToolAdapterError("RESPONSE_NOT_JSON") from exc
        if not isinstance(parsed, dict):
            raise ToolAdapterError("RESPONSE_NOT_OBJECT")
        return ToolAdapterResponse(status_code=status, body=parsed)


def _safe_close(connection: _HttpConnection) -> None:
    try:
        connection.close()
    except OSError:
        pass
