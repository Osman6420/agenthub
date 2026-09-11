"""Bounded MCP resource reads; no tools, filesystem dereference or server instructions."""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest, ToolAdapterUncertain
from apps.tools.egress import DnsResolver, EgressDenied, _default_resolver, validate_destination
from apps.tools.http_adapter import (
    BoundedHttpResponse,
    ConnectionFactory,
    _default_connection_factory,
    perform_bounded_https_request,
)
from apps.tools.tool_schema import ToolArtifactError, _validate_public_hostname

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_MIME_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/html",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)
_SESSION = re.compile(r"[\x21-\x7e]{1,1024}\Z")
_EVENT_SEPARATOR = re.compile(r"\r?\n\r?\n")
_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp-resource-dns")
_DNS_SLOTS = threading.BoundedSemaphore(4)


class McpResourceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class McpResourceLimits:
    max_items: int = 1000
    max_pages: int = 100
    max_requests: int = 1102
    max_response_bytes: int = 5_000_000
    max_resource_bytes: int = 4_000_000
    max_total_bytes: int = 100_000_000
    timeout_seconds: int = 30
    max_total_seconds: int = 300

    def validate(self) -> None:
        for value, lower, upper in (
            (self.max_items, 1, 5000),
            (self.max_pages, 1, 200),
            (self.max_requests, 3, 10_000),
            (self.max_response_bytes, 1024, 10_000_000),
            (self.max_resource_bytes, 1, 8_000_000),
            (self.max_total_bytes, 1024, 200_000_000),
            (self.timeout_seconds, 1, 60),
            (self.max_total_seconds, 1, 3600),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise McpResourceError("MCP_RESOURCE_LIMIT_INVALID")


@dataclass(frozen=True)
class McpResourceDocument:
    uri: str
    title: str
    mime_type: str
    content: bytes


def _uri(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 2048
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise McpResourceError("MCP_RESOURCE_URI_INVALID")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise McpResourceError("MCP_RESOURCE_URI_INVALID") from None
    if not parsed.scheme or parsed.username or parsed.password:
        raise McpResourceError("MCP_RESOURCE_URI_INVALID")
    path = parsed.path
    for _ in range(3):
        decoded = unquote(path)
        if "\\" in decoded or any(part in {".", ".."} for part in decoded.split("/")):
            raise McpResourceError("MCP_RESOURCE_URI_INVALID")
        if decoded == path:
            break
        path = decoded
    if unquote(path) != path:
        raise McpResourceError("MCP_RESOURCE_URI_INVALID")
    try:
        if len(value.encode("utf-8")) > 4096:
            raise McpResourceError("MCP_RESOURCE_URI_INVALID")
    except UnicodeError:
        raise McpResourceError("MCP_RESOURCE_URI_INVALID") from None
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise McpResourceError("MCP_RESOURCE_RESPONSE_INVALID")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise McpResourceError("MCP_RESOURCE_RESPONSE_INVALID")


def _json(raw: str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    except (ValueError, RecursionError):
        raise McpResourceError("MCP_RESOURCE_RESPONSE_INVALID") from None


class McpResourceClient:
    """One bounded snapshot attempt against an explicitly approved HTTPS destination.

    The caller owns profile/grant/secret resolution and supplies a live authorization
    callback before every request. Resource URIs are sent to that endpoint as opaque
    identifiers; they never select a network destination or a local file.
    """

    def __init__(
        self,
        *,
        destination: dict[str, Any],
        resource_prefixes: tuple[str, ...],
        mime_types: tuple[str, ...],
        before_request: Callable[[], None],
        credential: str = "",
        limits: McpResourceLimits | None = None,
        resolver: DnsResolver | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.limits = limits or McpResourceLimits()
        self.limits.validate()
        if not isinstance(destination, dict) or set(destination) - {
            "scheme",
            "host",
            "port",
            "path_prefix",
            "session",
        }:
            raise McpResourceError("MCP_RESOURCE_DESTINATION_INVALID")
        if destination.get("scheme") != "https":
            raise McpResourceError("MCP_RESOURCE_DESTINATION_INVALID")
        try:
            _validate_public_hostname(destination.get("host"))
        except ToolArtifactError:
            raise McpResourceError("MCP_RESOURCE_DESTINATION_INVALID") from None
        path = destination.get("path_prefix", "/")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or len(path) > 1024
            or "?" in path
            or "#" in path
            or "\\" in path
            or "%" in path
            or any(ord(c) <= 32 or ord(c) == 127 for c in path)
            or any(part in {".", ".."} for part in path.split("/"))
        ):
            raise McpResourceError("MCP_RESOURCE_DESTINATION_INVALID")
        if "session" in destination and not isinstance(destination["session"], bool):
            raise McpResourceError("MCP_RESOURCE_DESTINATION_INVALID")
        if not 1 <= len(resource_prefixes) <= 50:
            raise McpResourceError("MCP_RESOURCE_SCOPE_REQUIRED")
        for prefix in resource_prefixes:
            if not _uri(prefix).endswith("/"):
                raise McpResourceError("MCP_RESOURCE_PREFIX_INVALID")
        if (
            not mime_types
            or len(mime_types) > len(SUPPORTED_MIME_TYPES)
            or not set(mime_types) <= SUPPORTED_MIME_TYPES
        ):
            raise McpResourceError("MCP_RESOURCE_MIME_UNSUPPORTED")
        if (
            not isinstance(credential, str)
            or len(credential) > 8192
            or any(not 33 <= ord(c) <= 126 for c in credential)
        ):
            raise McpResourceError("MCP_RESOURCE_CREDENTIAL_INVALID")
        self._destination = dict(destination)
        self._prefixes = resource_prefixes
        self._mime_types = frozenset(mime_types)
        self._credential = credential
        self._authorize = before_request
        self._resolver = resolver
        self._factory = connection_factory or _default_connection_factory
        self._path = path
        self._session = ""
        self._next_id = 1
        self._requests = 0
        self._bytes = 0
        self._deadline: float | None = None
        self._initialized = False
        self._started = False
        self.snapshot_complete = False

    @property
    def fetched_bytes(self) -> int:
        return self._bytes

    def _resolve(self, host: str, port: int) -> list[tuple[Any, ...]]:
        # A blocked OS resolver cannot consume unlimited workers or enqueue unlimited
        # futures. Its slot is released by the resolver itself, including after timeout.
        if self._deadline is None or self._deadline <= time.monotonic():
            raise McpResourceError("MCP_RESOURCE_REQUEST_BUDGET_EXCEEDED")
        if not _DNS_SLOTS.acquire(blocking=False):
            raise EgressDenied("DNS_CAPACITY_EXCEEDED")

        def resolve() -> list[tuple[Any, ...]]:
            try:
                return (self._resolver or _default_resolver)(host, port)
            finally:
                _DNS_SLOTS.release()

        try:
            future = _DNS_POOL.submit(resolve)
        except RuntimeError:
            _DNS_SLOTS.release()
            raise EgressDenied("DNS_UNAVAILABLE") from None
        try:
            return future.result(
                timeout=max(0, min(self.limits.timeout_seconds, self._deadline - time.monotonic()))
            )
        except FutureTimeout:
            raise EgressDenied("DNS_DEADLINE_EXCEEDED") from None

    def _post(self, message: dict[str, Any], *, notification: bool = False) -> BoundedHttpResponse:
        self._authorize()
        if self._deadline is None:
            self._deadline = time.monotonic() + self.limits.max_total_seconds
        remaining = self._deadline - time.monotonic()
        if remaining < 1 or self._requests >= self.limits.max_requests:
            raise McpResourceError("MCP_RESOURCE_REQUEST_BUDGET_EXCEEDED")
        remaining_bytes = self.limits.max_total_bytes - self._bytes
        if remaining_bytes < 1:
            raise McpResourceError("MCP_RESOURCE_TOTAL_BYTES_EXCEEDED")
        self._requests += 1
        try:
            destination = validate_destination(self._destination, resolver=self._resolve)
            headers = {
                "Host": destination.host,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if self._credential:
                headers["Authorization"] = f"Bearer {self._credential}"
            if self._session:
                headers["Mcp-Session-Id"] = self._session
            if self._initialized:
                headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
            request = ToolAdapterRequest(
                protocol="mcp",
                method="POST",
                destination=destination,
                payload={},
                credential=None,
                timeout_seconds=min(self.limits.timeout_seconds, math.floor(remaining)),
                max_response_bytes=min(self.limits.max_response_bytes, remaining_bytes),
            )
            response = perform_bounded_https_request(
                self._factory,
                request,
                path=self._path,
                headers=headers,
                body=json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
                deadline=min(self._deadline, time.monotonic() + self.limits.timeout_seconds),
            )
        except (ToolAdapterError, ToolAdapterUncertain, EgressDenied) as exc:
            raise McpResourceError(f"MCP_RESOURCE_{exc.code}") from None
        self._bytes += len(response.body)
        if time.monotonic() > self._deadline:
            raise McpResourceError("MCP_RESOURCE_REQUEST_BUDGET_EXCEEDED")
        if response.status in {401, 403}:
            raise McpResourceError("MCP_RESOURCE_AUTH_FAILED")
        if notification:
            if response.status != 202 or response.body:
                raise McpResourceError("MCP_RESOURCE_NOTIFICATION_REJECTED")
        elif response.status != 200:
            raise McpResourceError("MCP_RESOURCE_UPSTREAM_STATUS")
        return response

    def _result(self, response: BoundedHttpResponse, request_id: int) -> dict[str, Any]:
        try:
            raw = response.body.decode("utf-8")
        except UnicodeDecodeError:
            raise McpResourceError("MCP_RESOURCE_RESPONSE_INVALID") from None
        content_type = response.content_type.split(";", 1)[0].strip().lower()
        if content_type == "application/json":
            messages = [_json(raw)]
        elif content_type == "text/event-stream":
            blocks = _EVENT_SEPARATOR.split(raw)
            if len(blocks) > 128:
                raise McpResourceError("MCP_RESOURCE_EVENT_LIMIT_EXCEEDED")
            messages = [
                _json(
                    "\n".join(
                        line[5:].lstrip(" ")
                        for line in block.splitlines()
                        if line.startswith("data:")
                    )
                )
                for block in blocks
                if any(line.startswith("data:") for line in block.splitlines())
            ]
        else:
            raise McpResourceError("MCP_RESOURCE_CONTENT_TYPE_INVALID")
        found = None
        for message in messages:
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise McpResourceError("MCP_RESOURCE_RESPONSE_INVALID")
            if "method" in message:
                if "id" in message or not str(message["method"]).startswith("notifications/"):
                    raise McpResourceError("MCP_RESOURCE_SERVER_REQUEST_UNSUPPORTED")
                continue
            identifier = message.get("id")
            if type(identifier) is not int or identifier != request_id or found is not None:
                raise McpResourceError("MCP_RESOURCE_RESPONSE_ID_INVALID")
            if "error" in message or not isinstance(message.get("result"), dict):
                raise McpResourceError("MCP_RESOURCE_RPC_ERROR")
            found = message["result"]
        if found is None:
            raise McpResourceError("MCP_RESOURCE_RESPONSE_INVALID")
        return found

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        response = self._post(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        result = self._result(response, request_id)
        if method == "initialize":
            if result.get("protocolVersion") != PROTOCOL_VERSION:
                raise McpResourceError("MCP_RESOURCE_PROTOCOL_UNSUPPORTED")
            capabilities = result.get("capabilities")
            if not isinstance(capabilities, dict) or not isinstance(
                capabilities.get("resources"), dict
            ):
                raise McpResourceError("MCP_RESOURCE_CAPABILITY_REQUIRED")
            if response.session_id and _SESSION.fullmatch(response.session_id) is None:
                raise McpResourceError("MCP_RESOURCE_SESSION_INVALID")
            if self._destination.get("session") and not response.session_id:
                raise McpResourceError("MCP_RESOURCE_SESSION_REQUIRED")
            self._session = response.session_id
            self._initialized = True
        return result

    def iter_documents(self) -> Iterator[McpResourceDocument]:
        if self._started:
            raise McpResourceError("MCP_RESOURCE_CLIENT_ALREADY_USED")
        self._started = True
        self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agenthub-resource-ingestion", "version": "1"},
            },
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, notification=True)
        cursor = ""
        cursors: set[str] = set()
        uris: set[str] = set()
        for _ in range(self.limits.max_pages):
            result = self._rpc("resources/list", {"cursor": cursor} if cursor else {})
            resources = result.get("resources")
            if not isinstance(resources, list):
                raise McpResourceError("MCP_RESOURCE_LIST_INVALID")
            for resource in resources:
                if not isinstance(resource, dict):
                    raise McpResourceError("MCP_RESOURCE_LIST_INVALID")
                uri = _uri(resource.get("uri"))
                if uri in uris or len(uris) >= self.limits.max_items:
                    raise McpResourceError("MCP_RESOURCE_ITEM_LIMIT_OR_DUPLICATE")
                uris.add(uri)
                if not any(uri.startswith(prefix) for prefix in self._prefixes):
                    continue
                title = resource.get("title", resource.get("name"))
                if not isinstance(title, str) or not 1 <= len(title) <= 500:
                    raise McpResourceError("MCP_RESOURCE_TITLE_INVALID")
                try:
                    title.encode("utf-8")
                except UnicodeError:
                    raise McpResourceError("MCP_RESOURCE_TITLE_INVALID") from None
                if any(ord(c) < 32 or ord(c) == 127 for c in title):
                    raise McpResourceError("MCP_RESOURCE_TITLE_INVALID")
                content = self._rpc("resources/read", {"uri": uri}).get("contents")
                if (
                    not isinstance(content, list)
                    or len(content) != 1
                    or not isinstance(content[0], dict)
                ):
                    raise McpResourceError("MCP_RESOURCE_CONTENTS_UNSUPPORTED")
                item = content[0]
                mime = item.get("mimeType", resource.get("mimeType"))
                if (
                    not isinstance(mime, str)
                    or mime not in self._mime_types
                    or (resource.get("mimeType") and mime != resource["mimeType"])
                ):
                    raise McpResourceError("MCP_RESOURCE_MIME_UNSUPPORTED")
                if item.get("uri") != uri or ("text" in item) == ("blob" in item):
                    raise McpResourceError("MCP_RESOURCE_CONTENT_INVALID")
                try:
                    if (
                        "text" in item
                        and isinstance(item["text"], str)
                        and mime.startswith("text/")
                    ):
                        data = item["text"].encode("utf-8")
                    elif "blob" in item and isinstance(item["blob"], str):
                        data = base64.b64decode(item["blob"], validate=True)
                        if mime.startswith("text/"):
                            data.decode("utf-8")
                    else:
                        raise McpResourceError("MCP_RESOURCE_CONTENT_INVALID")
                except (ValueError, UnicodeError, binascii.Error):
                    raise McpResourceError("MCP_RESOURCE_CONTENT_INVALID") from None
                if not data or len(data) > self.limits.max_resource_bytes:
                    raise McpResourceError("MCP_RESOURCE_CONTENT_TOO_LARGE")
                yield McpResourceDocument(uri=uri, title=title, mime_type=mime, content=data)
            cursor = result.get("nextCursor", "")
            if cursor == "":
                self.snapshot_complete = True
                return
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096 or cursor in cursors:
                raise McpResourceError("MCP_RESOURCE_CURSOR_INVALID")
            cursors.add(cursor)
        raise McpResourceError("MCP_RESOURCE_PAGE_LIMIT_EXCEEDED")
