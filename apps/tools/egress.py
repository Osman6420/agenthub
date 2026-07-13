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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from apps.tools.tool_schema import ToolArtifactError, _validate_public_hostname

# A resolver maps (host, port) to getaddrinfo-shaped tuples; injectable for tests.
DnsResolver = Callable[[str, int], list[tuple[Any, ...]]]

ALLOWED_SCHEMES = frozenset({"https"})
_CORPORATE_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


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


def validate_private_destination(
    destination: dict[str, Any],
    *,
    network_policy_id: str,
    network_policies: Mapping[str, Sequence[str]],
    resolver: DnsResolver | None = None,
) -> ValidatedDestination:
    """Validate a Confluence-only destination against a deployment-owned private policy.

    This is deliberately separate from :func:`validate_destination`; public-only callers cannot
    opt into private networking. The caller must supply the immutable profile's policy identifier,
    while the actual CIDRs come only from deployment configuration.
    """

    if not isinstance(destination, dict):
        raise EgressDenied("DESTINATION_INVALID")
    if destination.get("scheme") not in ALLOWED_SCHEMES:
        raise EgressDenied("SCHEME_NOT_ALLOWED")
    host = destination.get("host")
    validate_private_hostname(host)
    assert isinstance(host, str)  # noqa: S101 - narrowed by hostname validation
    port = destination.get("port", 443)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise EgressDenied("PORT_NOT_ALLOWED")

    networks = _private_networks_for_policy(network_policy_id, network_policies)
    resolve = resolver or _default_resolver
    try:
        infos = resolve(host, port)
    except OSError as exc:
        raise EgressDenied("DNS_RESOLUTION_FAILED") from exc
    addresses = _extract_addresses(infos)
    if not addresses:
        raise EgressDenied("DNS_RESOLUTION_EMPTY")
    for address in addresses:
        _assert_allowed_private_ip(address, networks)

    return ValidatedDestination(
        scheme="https",
        host=host,
        port=port,
        path_prefix=str(destination.get("path_prefix", "")),
        ip_addresses=tuple(sorted(addresses)),
    )


def validate_private_network_policy(
    network_policy_id: str, network_policies: Mapping[str, Sequence[str]]
) -> None:
    """Validate that a deployment-owned policy exists without resolving or opening a socket."""

    _private_networks_for_policy(network_policy_id, network_policies)


def validate_private_hostname(value: Any) -> None:
    """Validate a corporate FQDN shape without applying the public-suffix denylist."""

    if not isinstance(value, str) or not value or len(value) > 253:
        raise EgressDenied("HOST_NOT_ALLOWED")
    lowered = value.lower()
    try:
        ipaddress.ip_address(lowered)
    except ValueError:
        pass
    else:
        raise EgressDenied("HOST_NOT_ALLOWED")
    if lowered in {"localhost", "metadata", "metadata.google.internal"}:
        raise EgressDenied("HOST_NOT_ALLOWED")
    labels = lowered.split(".")
    if len(labels) < 2:
        raise EgressDenied("HOST_NOT_ALLOWED")
    for label in labels:
        if (
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(character.isalnum() or character == "-" for character in label)
        ):
            raise EgressDenied("HOST_NOT_ALLOWED")


def _private_networks_for_policy(
    policy_id: str, policies: Mapping[str, Sequence[str]]
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    if not isinstance(policy_id, str) or not policy_id or not isinstance(policies, Mapping):
        raise EgressDenied("NETWORK_POLICY_INVALID")
    configured = policies.get(policy_id)
    if (
        not isinstance(configured, Sequence)
        or isinstance(configured, (str, bytes))
        or not 1 <= len(configured) <= 64
    ):
        raise EgressDenied("NETWORK_POLICY_NOT_CONFIGURED")
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in configured:
        if not isinstance(cidr, str):
            raise EgressDenied("NETWORK_POLICY_INVALID")
        try:
            network = ipaddress.ip_network(cidr, strict=True)
        except ValueError as exc:
            raise EgressDenied("NETWORK_POLICY_INVALID") from exc
        if not _is_corporate_private_network(network):
            raise EgressDenied("NETWORK_POLICY_INVALID")
        networks.append(network)
    return tuple(networks)


def _is_corporate_private_network(
    network: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> bool:
    for private in _CORPORATE_PRIVATE_NETWORKS:
        if network.version != private.version:
            continue
        if network.subnet_of(private):  # type: ignore[arg-type]  # versions match above
            return True
    return False


def _assert_allowed_private_ip(
    address: str, networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise EgressDenied("DESTINATION_NOT_PRIVATE_ALLOWED") from exc
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not any(ip in private for private in _CORPORATE_PRIVATE_NETWORKS)
        or not any(ip in network for network in networks)
    ):
        raise EgressDenied("DESTINATION_NOT_PRIVATE_ALLOWED")


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
