"""SSRF/egress validation: only public unicast destinations are allowed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from apps.tools.egress import EgressDenied, validate_destination


def _resolver(*ips: str) -> Callable[[str, int], list[tuple[Any, ...]]]:
    def inner(host: str, port: int) -> list[tuple[Any, ...]]:
        return [(2, 1, 6, "", (ip, port)) for ip in ips]

    return inner


def _raising_resolver(host: str, port: int) -> list[tuple[Any, ...]]:
    raise OSError("dns down")


def _destination(**overrides: Any) -> dict[str, Any]:
    base = {"scheme": "https", "host": "api.example.com", "port": 443}
    base.update(overrides)
    return base


def test_public_destination_is_allowed() -> None:
    result = validate_destination(_destination(), resolver=_resolver("93.184.216.34"))
    assert result.host == "api.example.com"
    assert result.ip_addresses == ("93.184.216.34",)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # private
        "192.168.1.10",  # private
        "172.16.5.4",  # private
        "169.254.169.254",  # link-local / cloud metadata
        "0.0.0.0",  # noqa: S104  # unspecified
        "::1",  # ipv6 loopback
        "fd00::1",  # ipv6 unique-local
        "fe80::1",  # ipv6 link-local
    ],
)
def test_non_public_addresses_are_denied(ip: str) -> None:
    with pytest.raises(EgressDenied, match="DESTINATION_NOT_PUBLIC"):
        validate_destination(_destination(), resolver=_resolver(ip))


def test_any_private_address_in_the_set_denies() -> None:
    # DNS rebinding defense: a public + private mix must be denied.
    with pytest.raises(EgressDenied, match="DESTINATION_NOT_PUBLIC"):
        validate_destination(_destination(), resolver=_resolver("93.184.216.34", "10.0.0.1"))


def test_non_https_scheme_is_denied() -> None:
    with pytest.raises(EgressDenied, match="SCHEME_NOT_ALLOWED"):
        validate_destination(_destination(scheme="http"), resolver=_resolver("93.184.216.34"))


def test_ip_literal_host_is_denied() -> None:
    with pytest.raises(EgressDenied, match="HOST_NOT_ALLOWED"):
        validate_destination(
            _destination(host="93.184.216.34"), resolver=_resolver("93.184.216.34")
        )


def test_bad_port_is_denied() -> None:
    with pytest.raises(EgressDenied, match="PORT_NOT_ALLOWED"):
        validate_destination(_destination(port=0), resolver=_resolver("93.184.216.34"))


def test_empty_dns_result_is_denied() -> None:
    with pytest.raises(EgressDenied, match="DNS_RESOLUTION_EMPTY"):
        validate_destination(_destination(), resolver=_resolver())


def test_dns_failure_is_denied() -> None:
    with pytest.raises(EgressDenied, match="DNS_RESOLUTION_FAILED"):
        validate_destination(_destination(), resolver=_raising_resolver)
