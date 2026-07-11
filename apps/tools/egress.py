"""SSRF-safe destination validation for the tool execution proxy.

The tool registry (increment A) validates a destination's *shape* at author time.
This module performs the *runtime* egress decision: it re-checks the host, resolves
DNS through an injectable resolver, and denies unless **every** resolved address is a
public unicast IP. Validating the resolved IPs — not just the hostname — is the
defense against DNS rebinding and against a name that resolves to a private,
loopback, link-local, or cloud-metadata address (v3 plan §17 threat model).

No socket is opened here; the actual connection is the adapter's job and, in the
default configuration, is a deterministic no-egress stub.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.tools.tool_schema import ToolArtifactError, _validate_public_hostname

# A resolver maps (host, port) to getaddrinfo-shaped tuples; injectable for tests.
DnsResolver = Callable[[str, int], list[tuple[Any, ...]]]

ALLOWED_SCHEMES = frozenset({"https"})


class EgressDenied(RuntimeError):
    """Raised when a destination fails the runtime egress policy."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ValidatedDestination:
    scheme: str
    host: str
    port: int
    path_prefix: str
    ip_addresses: tuple[str, ...]


def _default_resolver(host: str, port: int) -> list[tuple[Any, ...]]:
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def validate_destination(
    destination: dict[str, Any], *, resolver: DnsResolver | None = None
) -> ValidatedDestination:
    if not isinstance(destination, dict):
        raise EgressDenied("DESTINATION_INVALID")
    scheme = destination.get("scheme")
    if scheme not in ALLOWED_SCHEMES:
        raise EgressDenied("SCHEME_NOT_ALLOWED")
    host = destination.get("host")
    try:
        _validate_public_hostname(host)
    except ToolArtifactError as exc:
        raise EgressDenied("HOST_NOT_ALLOWED") from exc
    assert isinstance(host, str)  # noqa: S101  # narrowed by _validate_public_hostname

    port = destination.get("port", 443)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise EgressDenied("PORT_NOT_ALLOWED")

    resolve = resolver or _default_resolver
    try:
        infos = resolve(host, port)
    except OSError as exc:
        raise EgressDenied("DNS_RESOLUTION_FAILED") from exc
    addresses = _extract_addresses(infos)
    if not addresses:
        raise EgressDenied("DNS_RESOLUTION_EMPTY")
    for address in addresses:
        _assert_public_ip(address)

    path_prefix = destination.get("path_prefix", "")
    return ValidatedDestination(
        scheme=scheme,
        host=host,
        port=port,
        path_prefix=str(path_prefix),
        ip_addresses=tuple(sorted(addresses)),
    )


def _extract_addresses(infos: list[tuple[Any, ...]]) -> set[str]:
    addresses: set[str] = set()
    for info in infos:
        try:
            sockaddr = info[4]
            address = sockaddr[0]
        except (IndexError, TypeError) as exc:
            raise EgressDenied("DNS_RESOLUTION_FAILED") from exc
        if isinstance(address, str) and address:
            addresses.add(address)
    return addresses


def _assert_public_ip(address: str) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise EgressDenied("DESTINATION_NOT_PUBLIC") from exc
    # ``is_global`` is the positive allowlist; the explicit checks make the denial
    # reason auditable and cover ranges some Python versions classify inconsistently.
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        raise EgressDenied("DESTINATION_NOT_PUBLIC")
