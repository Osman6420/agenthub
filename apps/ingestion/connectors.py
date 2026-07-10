"""Bounded, allowlisted source connectors."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import boto3
from botocore.config import Config
from django.conf import settings

from apps.ingestion.models import Source


class ConnectorError(RuntimeError):
    pass


@dataclass(frozen=True)
class RawDocument:
    uri: str
    content: bytes
    title: str = ""


class Connector(Protocol):
    def fetch(self, source: Source) -> list[RawDocument]: ...


class _DenyRedirects(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise ConnectorError("REDIRECT_DENIED")


def _validate_https_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConnectorError("URL_DENIED")
    allowed = set(settings.INGESTION_HTTP_ALLOWED_HOSTS)
    if parsed.hostname not in allowed:
        raise ConnectorError("HOST_DENIED")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ConnectorError("DNS_FAILED") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ConnectorError("ADDRESS_DENIED")


class HttpsConnector:
    def fetch(self, source: Source) -> list[RawDocument]:
        url = str(source.connector_config.get("url", ""))
        _validate_https_url(url)
        request = Request(url, headers={"User-Agent": "AgentHub-Ingestion/1"})  # noqa: S310
        try:
            opener = build_opener(_DenyRedirects)
            with opener.open(request, timeout=settings.INGESTION_HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
                length = response.headers.get("Content-Length")
                if length and int(length) > settings.INGESTION_MAX_SOURCE_BYTES:
                    raise ConnectorError("SOURCE_TOO_LARGE")
                content = response.read(settings.INGESTION_MAX_SOURCE_BYTES + 1)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError("FETCH_FAILED") from exc
        if len(content) > settings.INGESTION_MAX_SOURCE_BYTES:
            raise ConnectorError("SOURCE_TOO_LARGE")
        return [RawDocument(uri=url, content=content)]


class S3Connector:
    def fetch(self, source: Source) -> list[RawDocument]:
        configured_bucket = str(settings.OBJECT_STORE["bucket"])
        bucket = str(source.connector_config.get("bucket") or configured_bucket)
        key = str(source.connector_config.get("key", ""))
        tenant_prefix = f"{source.organization.slug}/"
        if (
            not bucket
            or bucket != configured_bucket
            or not key.startswith(tenant_prefix)
            or key.startswith("/")
            or ".." in key.split("/")
        ):
            raise ConnectorError("OBJECT_KEY_DENIED")
        client = boto3.client(
            "s3",
            endpoint_url=settings.OBJECT_STORE["endpoint_url"] or None,
            region_name=settings.OBJECT_STORE["region"],
            config=Config(
                connect_timeout=settings.INGESTION_HTTP_TIMEOUT_SECONDS,
                read_timeout=settings.INGESTION_HTTP_TIMEOUT_SECONDS,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
        try:
            response: dict[str, Any] = client.get_object(Bucket=bucket, Key=key)
            if int(response.get("ContentLength", 0)) > settings.INGESTION_MAX_SOURCE_BYTES:
                raise ConnectorError("SOURCE_TOO_LARGE")
            content = response["Body"].read(settings.INGESTION_MAX_SOURCE_BYTES + 1)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError("FETCH_FAILED") from exc
        if len(content) > settings.INGESTION_MAX_SOURCE_BYTES:
            raise ConnectorError("SOURCE_TOO_LARGE")
        return [RawDocument(uri=f"s3://{bucket}/{key}", content=content)]


CONNECTORS: dict[str, type[Connector]] = {"https": HttpsConnector, "s3": S3Connector}


def get_connector(name: str) -> Connector:
    connector = CONNECTORS.get(name)
    if connector is None:
        raise ConnectorError("CONNECTOR_UNSUPPORTED")
    return connector()
