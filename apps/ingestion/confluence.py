"""Bounded, profile-only Confluence Data Center REST client (ADR-0006)."""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.utils.dateparse import parse_datetime

from apps.ingestion.confluence_secrets import ConfluenceEnvSecretResolver
from apps.ingestion.models import ConfluenceProfile
from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest, ToolAdapterUncertain
from apps.tools.egress import DnsResolver, EgressDenied, validate_private_destination
from apps.tools.http_adapter import (
    BoundedHttpResponse,
    ConnectionFactory,
    _default_connection_factory,
    perform_bounded_https_request,
)
from apps.tools.secrets_resolver import SecretResolutionError, SecretResolver


class ConfluenceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ConfluencePage:
    page_id: str
    title: str
    version: int
    updated_at: datetime | None
    root_page_id: str


@dataclass(frozen=True)
class _TraversalItem:
    page: ConfluencePage
    depth: int
    is_root: bool


class ConfluenceDataCenterClient:
    def __init__(
        self,
        *,
        resolver: DnsResolver | None = None,
        connection_factory: ConnectionFactory | None = None,
        secret_resolver: SecretResolver | None = None,
        network_policies: Mapping[str, Sequence[str]] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._resolver = resolver
        self._factory = connection_factory or _default_connection_factory
        self._secrets = secret_resolver or ConfluenceEnvSecretResolver()
        self._network_policies = (
            network_policies
            if network_policies is not None
            else settings.CONFLUENCE_NETWORK_POLICIES
        )
        self._sleep = sleeper
        self._request_count = 0
        self._response_bytes = 0

    @property
    def fetched_bytes(self) -> int:
        return self._response_bytes

    def iter_pages(
        self,
        profile: ConfluenceProfile,
        *,
        root_page_ids: list[str],
        include_root: bool,
        excluded_page_ids: set[str],
    ) -> Iterator[ConfluencePage]:
        queue: deque[_TraversalItem] = deque()
        scheduled: set[str] = set()
        for root_page_id in root_page_ids:
            if root_page_id in excluded_page_ids or root_page_id in scheduled:
                continue
            try:
                page = self._get_page_metadata(profile, root_page_id, root_page_id)
            except ConfluenceError as exc:
                if exc.code in {"CONFLUENCE_PAGE_NOT_FOUND", "CONFLUENCE_PAGE_GONE"}:
                    continue
                raise
            scheduled.add(page.page_id)
            self._assert_page_budget(profile, scheduled)
            queue.append(_TraversalItem(page=page, depth=0, is_root=True))

        while queue:
            item = queue.popleft()
            if include_root or not item.is_root:
                yield item.page
            if item.depth >= profile.max_depth:
                continue
            for child in self._get_children(profile, item.page.page_id, item.page.root_page_id):
                if child.page_id in excluded_page_ids or child.page_id in scheduled:
                    continue
                scheduled.add(child.page_id)
                self._assert_page_budget(profile, scheduled)
                queue.append(_TraversalItem(page=child, depth=item.depth + 1, is_root=False))

    def get_page_body(
        self, profile: ConfluenceProfile, page_id: str, root_page_id: str
    ) -> tuple[ConfluencePage, bytes]:
        query = urlencode({"expand": "body.storage,version"})
        payload = self._request_json(
            profile,
            f"/rest/api/content/{page_id}?{query}",
        )
        page = self._parse_page(payload, root_page_id=root_page_id)
        if page.page_id != page_id:
            raise ConfluenceError("CONFLUENCE_PAGE_ID_MISMATCH")
        body = payload.get("body")
        storage = body.get("storage") if isinstance(body, dict) else None
        value = storage.get("value") if isinstance(storage, dict) else None
        if not isinstance(value, str):
            raise ConfluenceError("CONFLUENCE_BODY_INVALID")
        encoded = value.encode("utf-8")
        if not encoded or len(encoded) > profile.max_page_body_bytes:
            raise ConfluenceError("CONFLUENCE_BODY_SIZE_INVALID")
        return page, encoded

    def _get_page_metadata(
        self, profile: ConfluenceProfile, page_id: str, root_page_id: str
    ) -> ConfluencePage:
        query = urlencode({"expand": "version"})
        payload = self._request_json(profile, f"/rest/api/content/{page_id}?{query}")
        page = self._parse_page(payload, root_page_id=root_page_id)
        if page.page_id != page_id:
            raise ConfluenceError("CONFLUENCE_PAGE_ID_MISMATCH")
        return page

    def _get_children(
        self, profile: ConfluenceProfile, parent_page_id: str, root_page_id: str
    ) -> Iterator[ConfluencePage]:
        start = 0
        while True:
            query = urlencode({"start": start, "limit": profile.page_size, "expand": "version"})
            payload = self._request_json(
                profile,
                f"/rest/api/content/{parent_page_id}/child/page?{query}",
            )
            results = payload.get("results")
            size = payload.get("size")
            if (
                not isinstance(results, list)
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size != len(results)
                or size < 0
                or size > profile.page_size
            ):
                raise ConfluenceError("CONFLUENCE_CHILDREN_INVALID")
            for child in results:
                if not isinstance(child, dict):
                    raise ConfluenceError("CONFLUENCE_CHILDREN_INVALID")
                yield self._parse_page(child, root_page_id=root_page_id)
            if size < profile.page_size:
                return
            start += profile.page_size

    def _request_json(self, profile: ConfluenceProfile, rest_path: str) -> dict[str, Any]:
        try:
            destination = validate_private_destination(
                {
                    "scheme": profile.scheme,
                    "host": profile.host,
                    "port": profile.port,
                    "path_prefix": profile.context_path,
                },
                network_policy_id=profile.network_policy_id,
                network_policies=self._network_policies,
                resolver=self._resolver,
            )
            credential = self._secrets.resolve(profile.secret_ref)
        except EgressDenied as exc:
            raise ConfluenceError(exc.code) from exc
        except SecretResolutionError as exc:
            raise ConfluenceError(exc.code) from exc

        request = ToolAdapterRequest(
            protocol="http",
            method="GET",
            destination=destination,
            payload={},
            credential=credential,
            timeout_seconds=profile.timeout_seconds,
            max_response_bytes=profile.max_response_bytes,
        )
        host_header = destination.host
        if destination.port != 443:
            host_header = f"{host_header}:{destination.port}"
        path = profile.context_path + rest_path
        for attempt in range(profile.max_retries + 1):
            self._request_count += 1
            if self._request_count > profile.max_requests:
                raise ConfluenceError("CONFLUENCE_REQUEST_LIMIT_EXCEEDED")
            try:
                response = perform_bounded_https_request(
                    self._factory,
                    request,
                    path=path,
                    headers={
                        "Host": host_header,
                        "Authorization": f"Bearer {credential}",
                        "Accept": "application/json",
                        "User-Agent": "AgentHub-Confluence/1",
                    },
                )
            except ToolAdapterError as exc:
                if exc.code != "CONNECTION_FAILED":
                    raise ConfluenceError(exc.code) from exc
                if attempt < profile.max_retries:
                    self._sleep(float(2**attempt))
                    continue
                raise ConfluenceError("CONFLUENCE_UPSTREAM_UNAVAILABLE") from exc
            except ToolAdapterUncertain as exc:
                if attempt < profile.max_retries:
                    self._sleep(float(2**attempt))
                    continue
                raise ConfluenceError("CONFLUENCE_UPSTREAM_UNAVAILABLE") from exc
            if response.status in {429} or 500 <= response.status <= 599:
                if attempt < profile.max_retries:
                    self._sleep(float(2**attempt))
                    continue
                raise ConfluenceError("CONFLUENCE_UPSTREAM_UNAVAILABLE")
            return self._parse_json_response(profile, response)
        raise ConfluenceError("CONFLUENCE_UPSTREAM_UNAVAILABLE")

    def _parse_json_response(
        self, profile: ConfluenceProfile, response: BoundedHttpResponse
    ) -> dict[str, Any]:
        if response.status in {401, 403}:
            raise ConfluenceError("CONFLUENCE_AUTH_FAILED")
        if response.status == 404:
            raise ConfluenceError("CONFLUENCE_PAGE_NOT_FOUND")
        if response.status == 410:
            raise ConfluenceError("CONFLUENCE_PAGE_GONE")
        if response.status != 200:
            raise ConfluenceError("CONFLUENCE_UPSTREAM_STATUS")
        if not response.content_type.lower().startswith("application/json"):
            raise ConfluenceError("CONFLUENCE_RESPONSE_CONTENT_TYPE_INVALID")
        self._response_bytes += len(response.body)
        if self._response_bytes > profile.max_total_bytes:
            raise ConfluenceError("CONFLUENCE_TOTAL_BYTES_EXCEEDED")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ConfluenceError("CONFLUENCE_RESPONSE_NOT_JSON") from exc
        if not isinstance(payload, dict):
            raise ConfluenceError("CONFLUENCE_RESPONSE_INVALID")
        return payload

    @staticmethod
    def _parse_page(payload: dict[str, Any], *, root_page_id: str) -> ConfluencePage:
        page_id = payload.get("id")
        title = payload.get("title")
        version = payload.get("version")
        if (
            not isinstance(page_id, str)
            or not page_id.isdigit()
            or page_id.startswith("0")
            or len(page_id) > 64
            or payload.get("type") != "page"
            or payload.get("status") != "current"
            or not isinstance(title, str)
            or len(title) > 500
            or not isinstance(version, dict)
        ):
            raise ConfluenceError("CONFLUENCE_PAGE_INVALID")
        number = version.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ConfluenceError("CONFLUENCE_PAGE_INVALID")
        when = version.get("when")
        updated_at: datetime | None = None
        if when is not None:
            if not isinstance(when, str):
                raise ConfluenceError("CONFLUENCE_PAGE_INVALID")
            updated_at = parse_datetime(when)
            if updated_at is None or updated_at.tzinfo is None:
                raise ConfluenceError("CONFLUENCE_PAGE_INVALID")
        return ConfluencePage(
            page_id=page_id,
            title=title,
            version=number,
            updated_at=updated_at,
            root_page_id=root_page_id,
        )

    @staticmethod
    def _assert_page_budget(profile: ConfluenceProfile, scheduled: set[str]) -> None:
        if len(scheduled) > profile.max_pages:
            raise ConfluenceError("CONFLUENCE_PAGE_LIMIT_EXCEEDED")
