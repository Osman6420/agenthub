"""Bounded public-only HTTP client for governed generic REST pull profiles."""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from apps.ingestion.models import RestPullAuthMode, RestPullContract, RestPullProfile
from apps.ingestion.rest_schema import (
    RestContractError,
    render_path,
    render_tree,
    resolve_pointer,
    validate_contract,
    validate_source_inputs,
)
from apps.ingestion.rest_secrets import RestPullEnvSecretResolver
from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest, ToolAdapterUncertain
from apps.tools.egress import DnsResolver, EgressDenied, validate_destination
from apps.tools.http_adapter import (
    BoundedHttpResponse,
    ConnectionFactory,
    _default_connection_factory,
    perform_bounded_https_request,
)
from apps.tools.secrets_resolver import SecretResolutionError, SecretResolver


class RestPullError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RestPullItem:
    external_id: str
    revision: str
    title: str
    deleted: bool
    raw_content: Any


class GovernedRestClient:
    def __init__(
        self,
        *,
        resolver: DnsResolver | None = None,
        connection_factory: ConnectionFactory | None = None,
        secret_resolver: SecretResolver | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._resolver = resolver
        self._factory = connection_factory or _default_connection_factory
        self._secrets = secret_resolver or RestPullEnvSecretResolver()
        self._sleep = sleeper
        self._request_count = 0
        self._fetched_bytes = 0

    @property
    def fetched_bytes(self) -> int:
        return self._fetched_bytes

    def iter_items(
        self,
        profile: RestPullProfile,
        contract: RestPullContract,
        *,
        inputs: dict[str, Any],
    ) -> Iterator[RestPullItem]:
        definition = validate_contract(contract.definition)
        normalized = validate_source_inputs(definition, inputs)
        request_spec = definition["request"]
        if request_spec["method"] != profile.method:
            raise RestPullError("REST_PROFILE_METHOD_MISMATCH")
        response_spec = definition["response"]
        pagination = definition["pagination"]
        cursor = ""
        visited_cursors: set[str] = set()
        item_count = 0
        for page_index in range(profile.max_pages):
            page_number = page_index + 1
            page_size = int(pagination.get("page_size", 0))
            query = render_tree(
                request_spec.get("query", {}),
                normalized,
                page_number=page_number,
                offset=page_index * page_size,
                page_size=page_size,
                cursor=cursor,
            )
            if not isinstance(query, dict):
                raise RestPullError("REST_QUERY_MAPPING_INVALID")
            mode = pagination["mode"]
            if mode == "page_number":
                query[pagination["parameter"]] = page_number
            elif mode == "offset":
                query[pagination["parameter"]] = page_index * page_size
            elif mode == "cursor" and cursor:
                query[pagination["parameter"]] = cursor
            body = None
            if "body" in request_spec:
                rendered_body = render_tree(
                    request_spec["body"],
                    normalized,
                    page_number=page_number,
                    offset=page_index * page_size,
                    page_size=page_size,
                    cursor=cursor,
                )
                body = json.dumps(rendered_body, separators=(",", ":")).encode("utf-8")
            path = render_path(request_spec["path"], normalized)
            payload = self._request_json(profile, path=path, query=query, body=body)
            try:
                items = resolve_pointer(payload, response_spec["items_pointer"])
            except RestContractError as exc:
                raise RestPullError(exc.code) from exc
            if not isinstance(items, list) or len(items) > profile.max_items:
                raise RestPullError("REST_ITEMS_INVALID")
            for raw_item in items:
                if not isinstance(raw_item, dict):
                    raise RestPullError("REST_ITEM_INVALID")
                item_count += 1
                if item_count > profile.max_items:
                    raise RestPullError("REST_ITEM_LIMIT_EXCEEDED")
                yield self._map_item(response_spec, raw_item)
            if mode == "none" or not items:
                return
            if mode in {"page_number", "offset"} and len(items) < page_size:
                return
            if mode == "cursor":
                try:
                    next_cursor = resolve_pointer(payload, pagination["cursor_pointer"])
                except RestContractError as exc:
                    raise RestPullError(exc.code) from exc
                if next_cursor in {None, ""}:
                    return
                if not isinstance(next_cursor, (str, int)) or isinstance(next_cursor, bool):
                    raise RestPullError("REST_CURSOR_INVALID")
                cursor = str(next_cursor)
                if len(cursor) > 1024 or cursor in visited_cursors:
                    raise RestPullError("REST_CURSOR_INVALID_OR_CYCLIC")
                visited_cursors.add(cursor)
        raise RestPullError("REST_PAGE_LIMIT_EXCEEDED")

    def get_content(
        self,
        profile: RestPullProfile,
        contract: RestPullContract,
        item: RestPullItem,
        *,
        inputs: dict[str, Any],
    ) -> bytes:
        response_spec = contract.definition["response"]
        raw_content = item.raw_content
        detail = response_spec.get("detail")
        if detail is not None:
            if profile.method != "GET":
                raise RestPullError("REST_DETAIL_REQUIRES_GET_PROFILE")
            path = render_path(detail["path"], inputs, detail_id=item.external_id)
            payload = self._request_json(profile, path=path, query={}, body=None)
            try:
                raw_content = resolve_pointer(payload, detail["content_pointer"])
            except RestContractError as exc:
                raise RestPullError(exc.code) from exc
        encoding = response_spec["content_encoding"]
        if not isinstance(raw_content, str):
            raise RestPullError("REST_CONTENT_INVALID")
        if encoding == "utf8_text":
            content = raw_content.encode("utf-8")
        elif encoding == "base64":
            try:
                content = base64.b64decode(raw_content, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RestPullError("REST_CONTENT_BASE64_INVALID") from exc
        else:  # validation should make this unreachable; retain fail-closed behavior.
            raise RestPullError("REST_CONTENT_ENCODING_INVALID")
        if not content or len(content) > profile.max_decoded_item_bytes:
            raise RestPullError("REST_CONTENT_SIZE_INVALID")
        return content

    def _map_item(self, spec: dict[str, Any], raw: dict[str, Any]) -> RestPullItem:
        try:
            external = resolve_pointer(raw, spec["id_pointer"])
            revision = (
                resolve_pointer(raw, spec["revision_pointer"]) if "revision_pointer" in spec else ""
            )
            title = resolve_pointer(raw, spec["title_pointer"]) if "title_pointer" in spec else ""
            deleted = (
                resolve_pointer(raw, spec["deleted_pointer"])
                if "deleted_pointer" in spec
                else False
            )
            content = (
                resolve_pointer(raw, spec["content_pointer"]) if "content_pointer" in spec else None
            )
        except RestContractError as exc:
            raise RestPullError(exc.code) from exc
        if (
            not isinstance(external, (str, int))
            or isinstance(external, bool)
            or not str(external)
            or len(str(external)) > 256
        ):
            raise RestPullError("REST_EXTERNAL_ID_INVALID")
        if revision is None:
            revision = ""
        if (
            not isinstance(revision, (str, int))
            or isinstance(revision, bool)
            or len(str(revision)) > 256
        ):
            raise RestPullError("REST_REVISION_INVALID")
        if title is None:
            title = ""
        if not isinstance(title, str) or len(title) > 500 or not isinstance(deleted, bool):
            raise RestPullError("REST_ITEM_METADATA_INVALID")
        return RestPullItem(str(external), str(revision), title, deleted, content)

    def _request_json(
        self,
        profile: RestPullProfile,
        *,
        path: str,
        query: dict[str, Any],
        body: bytes | None,
    ) -> dict[str, Any] | list[Any]:
        try:
            destination = validate_destination(
                {
                    "scheme": profile.scheme,
                    "host": profile.host,
                    "port": profile.port,
                    "path_prefix": profile.path_prefix,
                },
                resolver=self._resolver,
            )
            credential = (
                self._secrets.resolve(profile.secret_ref)
                if profile.auth_mode != RestPullAuthMode.NONE
                else ""
            )
        except (EgressDenied, SecretResolutionError) as exc:
            raise RestPullError(exc.code) from exc
        host_header = (
            destination.host
            if destination.port == 443
            else f"{destination.host}:{destination.port}"
        )
        headers = {
            "Host": host_header,
            "Accept": "application/json",
            "User-Agent": "AgentHub-RestPull/1",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if profile.auth_mode == RestPullAuthMode.BEARER:
            headers["Authorization"] = f"Bearer {credential}"
        elif profile.auth_mode == RestPullAuthMode.API_KEY_HEADER:
            headers[profile.api_key_header_name] = credential
        request_path = _join_prefix(profile.path_prefix, path)
        encoded_query = urlencode(query, doseq=True)
        if encoded_query:
            request_path += "?" + encoded_query
        request = ToolAdapterRequest(
            protocol="http",
            method=profile.method,
            destination=destination,
            payload={},
            credential="",
            timeout_seconds=profile.timeout_seconds,
            max_response_bytes=profile.max_response_bytes,
        )
        retries = profile.max_retries if profile.method == "GET" else 0
        for attempt in range(retries + 1):
            self._request_count += 1
            if self._request_count > profile.max_requests:
                raise RestPullError("REST_REQUEST_LIMIT_EXCEEDED")
            try:
                response = perform_bounded_https_request(
                    self._factory, request, path=request_path, headers=headers, body=body
                )
            except ToolAdapterUncertain as exc:
                if profile.method == "GET" and attempt < retries:
                    self._sleep(float(2**attempt))
                    continue
                raise RestPullError(
                    "REST_POST_OUTCOME_UNKNOWN"
                    if profile.method == "POST"
                    else "REST_UPSTREAM_UNAVAILABLE"
                ) from exc
            except ToolAdapterError as exc:
                if (
                    exc.code == "CONNECTION_FAILED"
                    and profile.method == "GET"
                    and attempt < retries
                ):
                    self._sleep(float(2**attempt))
                    continue
                raise RestPullError(exc.code) from exc
            if (response.status == 429 or 500 <= response.status <= 599) and attempt < retries:
                self._sleep(float(2**attempt))
                continue
            return self._parse_json(profile, response)
        raise RestPullError("REST_UPSTREAM_UNAVAILABLE")

    def _parse_json(
        self, profile: RestPullProfile, response: BoundedHttpResponse
    ) -> dict[str, Any] | list[Any]:
        if response.status in {401, 403}:
            raise RestPullError("REST_AUTH_FAILED")
        if response.status == 404:
            raise RestPullError("REST_RESOURCE_NOT_FOUND")
        if not 200 <= response.status < 300:
            raise RestPullError("REST_UPSTREAM_STATUS")
        if not response.content_type.lower().startswith("application/json"):
            raise RestPullError("REST_RESPONSE_CONTENT_TYPE_INVALID")
        self._fetched_bytes += len(response.body)
        if self._fetched_bytes > profile.max_total_bytes:
            raise RestPullError("REST_TOTAL_BYTES_EXCEEDED")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RestPullError("REST_RESPONSE_NOT_JSON") from exc
        if not isinstance(payload, (dict, list)):
            raise RestPullError("REST_RESPONSE_INVALID")
        return payload


def _join_prefix(prefix: str, path: str) -> str:
    if prefix == "/":
        return path
    return prefix.rstrip("/") + path
