"""Real HTTPS transport for tool adapters (stdlib only), enabled by configuration.

SSRF-safe by construction: connects to the *already-validated public IP* from the
egress check while verifying the TLS certificate and sending SNI/Host for the original
hostname, closing the DNS-rebinding TOCTOU window. Redirects are never followed, the
response body is read under a hard byte cap, and a timeout after dispatch is surfaced
as an uncertain outcome (never a false success).

``perform_https_post`` is the shared, injectable transport used by both the HTTP and
MCP adapters; the connection factory is injectable so tests run fully offline.
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class BoundedHttpResponse:
    status: int
    body: bytes
    content_type: str
    # Captured for MCP Streamable HTTP session support; empty for every other response.
    session_id: str = ""


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Dials a fixed IP while verifying the certificate for the original hostname."""

    def __init__(
        self, ip: str, port: int, *, server_hostname: str, timeout: float, context: ssl.SSLContext
    ) -> None:
        super().__init__(server_hostname, port, timeout=timeout, context=context)
        self._pinned_ip = ip
        self._ssl_context = context
        self._timeout_seconds = timeout
        self._deadline: float | None = None

    def set_deadline(self, deadline: float) -> None:
        self._deadline = deadline

    def _connect_timeout(self) -> float:
        if self._deadline is None:
            return self._timeout_seconds
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request deadline exceeded")
        return min(self._timeout_seconds, remaining)

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), self._connect_timeout())
        # ``self.host`` is the original hostname → SNI + cert hostname verification.
        if self._deadline is None:
            self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)
        else:
            # Expose the socket to deadline cancellation before a potentially slow
            # TLS handshake. Certificate and hostname verification remain unchanged.
            self.sock = sock
            tls_sock = self._ssl_context.wrap_socket(
                sock, server_hostname=self.host, do_handshake_on_connect=False
            )
            self.sock = tls_sock
            tls_sock.settimeout(self._connect_timeout())
            tls_sock.do_handshake()


def _default_connection_factory(
    ip: str, port: int, timeout: float, server_hostname: str
) -> _HttpConnection:
    context = ssl.create_default_context()
    return _PinnedHTTPSConnection(
        ip, port, server_hostname=server_hostname, timeout=timeout, context=context
    )


def perform_https_post(
    factory: ConnectionFactory,
    request: ToolAdapterRequest,
    *,
    path: str,
    headers: dict[str, str],
    body: bytes,
) -> bytes:
    """Send a bounded, redirect-free HTTPS request to the validated IP; return 2xx bytes."""
    response = perform_bounded_https_request(
        factory, request, path=path, headers=headers, body=body
    )
    if not 200 <= response.status < 300:
        raise ToolAdapterError("UPSTREAM_STATUS")
    return response.body


def perform_bounded_https_request(
    factory: ConnectionFactory,
    request: ToolAdapterRequest,
    *,
    path: str,
    headers: dict[str, str],
    body: bytes | None = None,
    deadline: float | None = None,
) -> BoundedHttpResponse:
    """Send one bounded redirect-free HTTPS request and return status/content metadata.

    The caller owns endpoint-specific status handling. This lower-level seam exists for governed
    asynchronous APIs (OCR submit/poll/result/ack); it retains the same validated-IP pinning, TLS,
    timeout, redirect and response-size controls as ``perform_https_post``.
    """
    destination = request.destination
    if not destination.ip_addresses:
        raise ToolAdapterError("DESTINATION_UNRESOLVED")
    ip = destination.ip_addresses[0]
    method = request.method or "POST"
    connection = factory(ip, destination.port, float(request.timeout_seconds), destination.host)
    expired = threading.Event()
    active_socket: list[Any] = [None]
    timer = None
    if deadline is not None:
        if deadline <= time.monotonic():
            _safe_close(connection)
            raise ToolAdapterError("REQUEST_DEADLINE_EXCEEDED")
        configure_deadline = getattr(connection, "set_deadline", None)
        if configure_deadline is not None:
            configure_deadline(deadline)

        def abort() -> None:
            expired.set()
            sock = active_socket[0] or getattr(connection, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            _safe_close(connection)

        timer = threading.Timer(deadline - time.monotonic(), abort)
        timer.daemon = True
        timer.start()
    try:
        connection.request(method, path, body=body, headers=headers)
        active_socket[0] = getattr(connection, "sock", None)
        response = connection.getresponse()
        status = int(response.status)
        raw = response.read(request.max_response_bytes + 1)
        getheader = getattr(response, "getheader", None)
        content_type = str(getheader("Content-Type", "") or "") if getheader else ""
        session_id = str(getheader("Mcp-Session-Id", "") or "") if getheader else ""
    except TimeoutError as exc:
        # Dispatched, but the outcome cannot be confirmed: never a false success.
        code = (
            "REQUEST_DEADLINE_EXCEEDED"
            if expired.is_set() or (deadline is not None and time.monotonic() >= deadline)
            else "OUTCOME_UNKNOWN"
        )
        raise ToolAdapterUncertain(code) from exc
    except OSError as exc:
        if expired.is_set():
            raise ToolAdapterUncertain("REQUEST_DEADLINE_EXCEEDED") from exc
        raise ToolAdapterError("CONNECTION_FAILED") from exc
    except ValueError as exc:
        if expired.is_set():
            raise ToolAdapterUncertain("REQUEST_DEADLINE_EXCEEDED") from exc
        raise
    except http.client.HTTPException as exc:
        if expired.is_set():
            raise ToolAdapterUncertain("REQUEST_DEADLINE_EXCEEDED") from exc
        if deadline is not None:
            raise ToolAdapterError("RESPONSE_INCOMPLETE") from exc
        raise
    finally:
        if timer is not None:
            timer.cancel()
        _safe_close(connection)

    if expired.is_set() or (deadline is not None and time.monotonic() > deadline):
        raise ToolAdapterUncertain("REQUEST_DEADLINE_EXCEEDED")
    if 300 <= status < 400:
        raise ToolAdapterError("REDIRECT_NOT_ALLOWED")
    if len(raw) > request.max_response_bytes:
        raise ToolAdapterError("RESPONSE_TOO_LARGE")
    return BoundedHttpResponse(
        status=status, body=raw, content_type=content_type, session_id=session_id
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
        path = destination.path_prefix or "/"
        headers = {
            "Host": destination.host,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if request.credential:
            headers["Authorization"] = f"Bearer {request.credential}"
        body = json.dumps(request.payload, separators=(",", ":")).encode("utf-8")

        raw = perform_https_post(self._factory, request, path=path, headers=headers, body=body)
        try:
            parsed: Any = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ToolAdapterError("RESPONSE_NOT_JSON") from exc
        if not isinstance(parsed, dict):
            raise ToolAdapterError("RESPONSE_NOT_OBJECT")
        return ToolAdapterResponse(status_code=200, body=parsed)


def _safe_close(connection: _HttpConnection) -> None:
    try:
        connection.close()
    except OSError:
        pass
