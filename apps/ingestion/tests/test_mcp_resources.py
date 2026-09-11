"""Offline protocol/egress tests with the real bounded HTTP adapter."""

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from apps.ingestion.mcp_resources import (
    PROTOCOL_VERSION,
    McpResourceClient,
    McpResourceError,
    McpResourceLimits,
)
from apps.tools.egress import EgressDenied


class Response:
    def __init__(self, *, status=200, body=b"", content_type="application/json", session=""):
        self.status, self.body = status, body
        self.content_type, self.session = content_type, session

    def read(self, amount):
        return self.body[:amount]

    def getheader(self, name, default=None):
        return {"Content-Type": self.content_type, "Mcp-Session-Id": self.session}.get(
            name, default
        )


class Harness:
    def __init__(self, *, sse=False, session="", transform=None):
        self.sse, self.session, self.transform = sse, session, transform
        self.requests, self.connections = [], []
        self.resources = [{"uri": "file:///kb/a", "name": "A", "mimeType": "text/plain"}]
        self.contents = {
            "file:///kb/a": [
                {"uri": "file:///kb/a", "mimeType": "text/plain", "text": "bounded source"}
            ]
        }
        self.capabilities: dict[str, dict[str, object]] = {"resources": {}}
        self.version = PROTOCOL_VERSION
        self.next_cursor = None

    def response(self, message, headers):
        result: dict[str, Any]
        method = message["method"]
        if method == "notifications/initialized":
            return Response(status=202)
        if method == "initialize":
            result = {
                "protocolVersion": self.version,
                "capabilities": self.capabilities,
                "serverInfo": {"name": "synthetic", "version": "1"},
                "instructions": "untrusted server instructions must be ignored",
            }
        elif method == "resources/list":
            result = {"resources": self.resources}
            if self.next_cursor is not None:
                result["nextCursor"] = self.next_cursor
        elif method == "resources/read":
            result = {"contents": self.contents[message["params"]["uri"]]}
        else:
            pytest.fail(f"unexpected method: {method}")
        envelope = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        if self.transform is not None:
            envelope = self.transform(method, envelope)
        body = json.dumps(envelope).encode()
        content_type = "application/json"
        if self.sse:
            body = (
                b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n'
                b"data: " + body + b"\n\n"
            )
            content_type = "text/event-stream; charset=utf-8"
        return Response(
            body=body,
            content_type=content_type,
            session=self.session if method == "initialize" else "",
        )

    def factory(self, ip, port, timeout, server_hostname):
        self.connections.append((ip, port, timeout, server_hostname))
        harness = self

        class Connection:
            def request(self, method, url, body=None, headers=None):
                self.message, self.headers = json.loads(body), headers
                harness.requests.append((method, url, self.message, headers))

            def getresponse(self):
                return harness.response(self.message, self.headers)

            def close(self):
                pass

        return Connection()


def client(harness, **overrides):
    args = {
        "destination": {"scheme": "https", "host": "mcp.example.com", "path_prefix": "/mcp"},
        "resource_prefixes": ("file:///kb/",),
        "mime_types": ("text/plain",),
        "before_request": lambda: None,
        "resolver": lambda host, port: [(2, 1, 6, "", ("93.184.216.34", port))],
        "connection_factory": harness.factory,
    }
    return McpResourceClient(**(args | overrides))


@pytest.mark.parametrize("sse", [False, True])
@pytest.mark.parametrize("session", ["", "opaque-session"])
def test_resource_scan_negotiates_then_reads_only_approved_endpoint(sse, session):
    harness = Harness(sse=sse, session=session)
    checks = []
    instance = client(
        harness, before_request=lambda: checks.append(True), credential="synthetic-token"
    )
    documents = list(instance.iter_documents())
    assert instance.snapshot_complete and len(documents) == 1
    assert documents[0].uri == "file:///kb/a" and documents[0].content == b"bounded source"
    assert len(checks) == 4
    assert [row[2]["method"] for row in harness.requests] == [
        "initialize",
        "notifications/initialized",
        "resources/list",
        "resources/read",
    ]
    assert all(row[:2] == ("POST", "/mcp") for row in harness.requests)
    assert all(
        row[0] == "93.184.216.34" and row[3] == "mcp.example.com" for row in harness.connections
    )
    assert "MCP-Protocol-Version" not in harness.requests[0][3]
    for _, _, _, headers in harness.requests[1:]:
        assert headers["MCP-Protocol-Version"] == PROTOCOL_VERSION
        assert headers["Authorization"] == "Bearer synthetic-token"
        assert headers.get("Mcp-Session-Id", "") == session
    with pytest.raises(McpResourceError, match="CLIENT_ALREADY_USED"):
        list(instance.iter_documents())


@pytest.mark.parametrize("capabilities", [{}, {"tools": {}}, {"resources": True}])
def test_tool_capability_does_not_authorize_resources(capabilities):
    harness = Harness()
    harness.capabilities = capabilities
    with pytest.raises(McpResourceError, match="CAPABILITY_REQUIRED"):
        list(client(harness).iter_documents())
    assert len(harness.requests) == 1


def test_unsupported_protocol_does_not_downgrade():
    harness = Harness()
    harness.version = "2024-11-05"
    with pytest.raises(McpResourceError, match="PROTOCOL_UNSUPPORTED"):
        list(client(harness).iter_documents())


@pytest.mark.parametrize("identifier", [True, None, 999, "1"])
def test_rpc_response_id_is_exact_and_typed(identifier):
    harness = Harness(transform=lambda method, envelope: envelope | {"id": identifier})
    with pytest.raises(McpResourceError, match="RESPONSE_ID_INVALID"):
        list(client(harness).iter_documents())


def test_server_requests_are_never_executed():
    harness = Harness(
        transform=lambda method, envelope: {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sampling/createMessage",
            "params": {},
        }
    )
    with pytest.raises(McpResourceError, match="SERVER_REQUEST_UNSUPPORTED"):
        list(client(harness).iter_documents())


def test_prefix_scope_skips_foreign_resource_without_reading_it():
    harness = Harness()
    harness.resources.insert(0, {"uri": "file:///private/a", "name": "Secret"})
    instance = client(harness)
    assert len(list(instance.iter_documents())) == 1
    reads = [row[2]["params"] for row in harness.requests if row[2]["method"] == "resources/read"]
    assert reads == [{"uri": "file:///kb/a"}]
    assert instance.snapshot_complete


@pytest.mark.parametrize(
    "uri", ["file:///kb/../private/a", "file:///kb/%2e%2e/private/a", "file:///kb/a\n", "relative"]
)
def test_invalid_or_traversing_resource_uri_is_closed(uri):
    harness = Harness()
    harness.resources = [{"uri": uri, "name": "Unsafe"}]
    with pytest.raises(McpResourceError, match="URI_INVALID"):
        list(client(harness).iter_documents())


@pytest.mark.parametrize(
    "mutation,code",
    [
        ({"uri": "file:///private/elsewhere"}, "CONTENT_INVALID"),
        ({"mimeType": "application/x-executable"}, "MIME_UNSUPPORTED"),
        ({"mimeType": {}}, "MIME_UNSUPPORTED"),
        ({"blob": "YQ=="}, "CONTENT_INVALID"),
        ({"text": "x" * 50}, "CONTENT_TOO_LARGE"),
    ],
)
def test_content_must_match_uri_mime_and_decoded_budget(mutation, code):
    harness = Harness()
    harness.contents["file:///kb/a"][0].update(mutation)
    instance = client(harness, limits=replace(McpResourceLimits(), max_resource_bytes=20))
    with pytest.raises(McpResourceError, match=code):
        list(instance.iter_documents())
    assert not instance.snapshot_complete


def test_binary_resource_is_decoded_under_the_same_contract():
    harness = Harness()
    harness.resources[0]["mimeType"] = "application/pdf"
    harness.contents["file:///kb/a"] = [
        {
            "uri": "file:///kb/a",
            "mimeType": "application/pdf",
            "blob": base64.b64encode(b"%PDF-synthetic").decode(),
        }
    ]
    documents = list(client(harness, mime_types=("application/pdf",)).iter_documents())
    assert documents[0].content == b"%PDF-synthetic"


def test_incomplete_pagination_never_marks_snapshot_complete():
    harness = Harness()
    harness.resources = []
    harness.next_cursor = "again"
    instance = client(harness)
    with pytest.raises(McpResourceError, match="CURSOR_INVALID"):
        list(instance.iter_documents())
    assert not instance.snapshot_complete


def test_reauthorization_failure_stops_before_next_request():
    harness = Harness()

    def authorize():
        if len(harness.requests) >= 3:
            raise PermissionError("grant revoked")

    instance = client(harness, before_request=authorize)
    with pytest.raises(PermissionError, match="grant revoked"):
        list(instance.iter_documents())
    assert len(harness.requests) == 3 and not instance.snapshot_complete


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "10.0.0.1"])
def test_private_or_metadata_destination_never_opens_connection(ip):
    harness = Harness()
    instance = client(harness, resolver=lambda host, port: [(2, 1, 6, "", (ip, port))])
    with pytest.raises(McpResourceError):
        list(instance.iter_documents())
    assert not harness.connections


def test_session_value_cannot_inject_headers():
    harness = Harness(session="ok\r\nX-Injection: yes")
    with pytest.raises(McpResourceError, match="SESSION_INVALID"):
        list(client(harness).iter_documents())
    assert len(harness.requests) == 1


def test_request_budget_stops_before_read_and_response_cap_is_enforced():
    harness = Harness()
    instance = client(harness, limits=replace(McpResourceLimits(), max_requests=3))
    with pytest.raises(McpResourceError, match="REQUEST_BUDGET_EXCEEDED"):
        list(instance.iter_documents())
    assert len(harness.requests) == 3
    harness.contents["file:///kb/a"][0]["text"] = "x" * 5000
    with pytest.raises(McpResourceError, match="RESPONSE_TOO_LARGE"):
        list(
            client(
                harness, limits=replace(McpResourceLimits(), max_response_bytes=1024)
            ).iter_documents()
        )


@pytest.mark.parametrize(
    "body", [b'{"jsonrpc":"2.0","id":1,"id":1,"result":{}}', b'{"x":NaN}', b"\xff"]
)
def test_ambiguous_or_non_utf8_json_is_rejected(body, monkeypatch):
    harness = Harness()
    monkeypatch.setattr(harness, "response", lambda message, headers: Response(body=body))
    with pytest.raises(McpResourceError, match="RESPONSE_INVALID"):
        list(client(harness).iter_documents())


def test_stalled_dns_has_a_deadline_and_bounded_capacity(monkeypatch):
    released = threading.Event()
    calls = []

    def resolver(host, port):
        calls.append(host)
        released.wait(2)
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr("apps.ingestion.mcp_resources._DNS_POOL", pool)
        monkeypatch.setattr(
            "apps.ingestion.mcp_resources._DNS_SLOTS", threading.BoundedSemaphore(1)
        )
        instance = client(Harness(), resolver=resolver)
        instance._deadline = time.monotonic() + 0.03
        try:
            with pytest.raises(EgressDenied, match="DNS_DEADLINE_EXCEEDED"):
                instance._resolve("mcp.example.com", 443)
            instance._deadline = time.monotonic() + 1
            with pytest.raises(EgressDenied, match="DNS_CAPACITY_EXCEEDED"):
                instance._resolve("mcp.example.com", 443)
            assert calls == ["mcp.example.com"]
        finally:
            released.set()


@pytest.mark.parametrize("title", ["bad\x00name", "bad\ud800name"])
def test_title_cannot_break_persistence_or_encoding(title):
    harness = Harness()
    harness.resources[0]["name"] = title
    with pytest.raises(McpResourceError, match="TITLE_INVALID"):
        list(client(harness).iter_documents())
    assert not any(row[2]["method"] == "resources/read" for row in harness.requests)


def test_nested_encoded_path_cannot_expand_resource_scope():
    harness = Harness()
    harness.resources[0]["uri"] = "file:///kb/%252525252e%252525252e/private"
    with pytest.raises(McpResourceError, match="URI_INVALID"):
        list(client(harness).iter_documents())
