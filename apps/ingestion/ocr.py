"""Profile-ID-only client for the owner-approved asynchronous Markdown OCR API."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from apps.ingestion.models import OcrProfile
from apps.ingestion.ocr_secrets import OcrEnvSecretResolver
from apps.tools.adapters import ToolAdapterError, ToolAdapterRequest, ToolAdapterUncertain
from apps.tools.egress import DnsResolver, EgressDenied, validate_destination
from apps.tools.http_adapter import (
    BoundedHttpResponse,
    ConnectionFactory,
    _default_connection_factory,
    perform_bounded_https_request,
)
from apps.tools.secrets_resolver import SecretResolutionError, SecretResolver

_TERMINAL_FAILURES = frozenset({"FAILED", "ACKNOWLEDGED", "EXPIRED"})
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class OcrError(RuntimeError):
    def __init__(self, code: str, *, upstream_code: str = "") -> None:
        self.code = code
        self.upstream_code = upstream_code
        super().__init__(code)


class OcrOutcomeUnknown(OcrError):
    """The non-idempotent submit may have reached the service; never blindly resubmit."""


class AsyncMarkdownOcrClient:
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
        self._secrets = secret_resolver or OcrEnvSecretResolver()
        self._sleep = sleeper

    def submit(self, profile: OcrProfile, pdf: bytes) -> uuid.UUID:
        if len(pdf) > profile.max_upload_bytes:
            raise OcrError("OCR_UPLOAD_TOO_LARGE")
        boundary = f"agenthub-{uuid.uuid4().hex}"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="document.pdf"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode("ascii")
            + pdf
            + f"\r\n--{boundary}--\r\n".encode("ascii")
        )
        try:
            response = self._request(
                profile,
                method="POST",
                path="/ocr-jobs",
                body=body,
                content_type=f"multipart/form-data; boundary={boundary}",
                max_response_bytes=min(profile.max_result_bytes, 1_000_000),
            )
        except ToolAdapterUncertain as exc:
            raise OcrOutcomeUnknown("OCR_SUBMIT_OUTCOME_UNKNOWN") from exc
        except ToolAdapterError as exc:
            raise OcrError(exc.code) from exc
        if response.status != 202:
            raise OcrError(self._status_code(response.status, "OCR_SUBMIT_FAILED"))
        payload = self._json_object(response)
        try:
            job_id = uuid.UUID(str(payload["job_id"]))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise OcrError("OCR_RESPONSE_INVALID") from exc
        if payload.get("status") != "QUEUED":
            raise OcrError("OCR_RESPONSE_INVALID")
        return job_id

    def wait_for_success(self, profile: OcrProfile, job_id: uuid.UUID) -> None:
        for attempt in range(profile.max_poll_attempts):
            try:
                response = self._request(
                    profile,
                    method="GET",
                    path=f"/ocr-jobs/{job_id}",
                    max_response_bytes=min(profile.max_result_bytes, 1_000_000),
                )
            except ToolAdapterError as exc:
                if exc.code != "CONNECTION_FAILED":
                    raise OcrError(exc.code) from exc
                if attempt + 1 == profile.max_poll_attempts:
                    raise OcrError("OCR_POLL_EXHAUSTED") from None
                self._sleep(float(profile.poll_interval_seconds))
                continue
            except ToolAdapterUncertain:
                if attempt + 1 == profile.max_poll_attempts:
                    raise OcrError("OCR_POLL_EXHAUSTED") from None
                self._sleep(float(profile.poll_interval_seconds))
                continue
            if response.status == 503:
                if attempt + 1 == profile.max_poll_attempts:
                    raise OcrError("OCR_POLL_EXHAUSTED")
                self._sleep(float(profile.poll_interval_seconds))
                continue
            if response.status != 200:
                raise OcrError(self._status_code(response.status, "OCR_POLL_FAILED"))
            payload = self._json_object(response)
            if str(payload.get("job_id", "")) != str(job_id):
                raise OcrError("OCR_RESPONSE_INVALID")
            status = payload.get("status")
            if status == "SUCCEEDED":
                return
            if status == "FAILED":
                upstream_code = payload.get("error_code")
                if not isinstance(upstream_code, str) or not _ERROR_CODE.fullmatch(upstream_code):
                    upstream_code = "UNKNOWN"
                raise OcrError("OCR_JOB_FAILED", upstream_code=upstream_code)
            if status in _TERMINAL_FAILURES:
                raise OcrError(f"OCR_JOB_{status}")
            if status not in {"QUEUED", "PROCESSING"}:
                raise OcrError("OCR_RESPONSE_INVALID")
            if attempt + 1 < profile.max_poll_attempts:
                self._sleep(float(profile.poll_interval_seconds))
        raise OcrError("OCR_POLL_EXHAUSTED")

    def download(self, profile: OcrProfile, job_id: uuid.UUID) -> bytes:
        try:
            response = self._request(
                profile,
                method="GET",
                path=f"/ocr-jobs/{job_id}/result",
                max_response_bytes=profile.max_result_bytes,
                accept="text/markdown",
            )
        except ToolAdapterUncertain as exc:
            raise OcrError("OCR_RESULT_READ_FAILED") from exc
        except ToolAdapterError as exc:
            raise OcrError(exc.code) from exc
        if response.status != 200:
            raise OcrError(self._status_code(response.status, "OCR_RESULT_FAILED"))
        if not response.content_type.lower().startswith("text/markdown"):
            raise OcrError("OCR_RESULT_CONTENT_TYPE_INVALID")
        try:
            response.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OcrError("OCR_RESULT_NOT_UTF8") from exc
        if not response.body.strip():
            raise OcrError("OCR_RESULT_EMPTY")
        return response.body

    def acknowledge(self, profile: OcrProfile, job_id: uuid.UUID) -> None:
        # ACK is explicitly idempotent in the approved contract; one retry is safe.
        for attempt in range(2):
            try:
                response = self._request(
                    profile,
                    method="POST",
                    path=f"/ocr-jobs/{job_id}/ack",
                    body=b"",
                    max_response_bytes=1_024,
                )
            except (ToolAdapterError, ToolAdapterUncertain):
                if attempt == 0:
                    continue
                raise OcrError("OCR_ACK_FAILED") from None
            if response.status in {204, 410}:
                return
            if response.status == 503 and attempt == 0:
                continue
            raise OcrError(self._status_code(response.status, "OCR_ACK_FAILED"))

    def _request(
        self,
        profile: OcrProfile,
        *,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str = "application/json",
        accept: str = "application/json",
        max_response_bytes: int,
    ) -> BoundedHttpResponse:
        try:
            destination = validate_destination(
                {
                    "scheme": profile.scheme,
                    "host": profile.host,
                    "port": profile.port,
                    "path_prefix": profile.base_path,
                },
                resolver=self._resolver,
            )
            credential = self._secrets.resolve(profile.secret_ref)
        except EgressDenied as exc:
            raise OcrError(exc.code) from exc
        except SecretResolutionError as exc:
            raise OcrError(exc.code) from exc
        request = ToolAdapterRequest(
            protocol="http",
            method=method,
            destination=destination,
            payload={},
            credential=credential,
            timeout_seconds=profile.timeout_seconds,
            max_response_bytes=max_response_bytes,
        )
        return perform_bounded_https_request(
            self._factory,
            request,
            path=profile.base_path + path,
            headers={
                "Host": destination.host,
                "Authorization": f"Bearer {credential}",
                "Content-Type": content_type,
                "Accept": accept,
            },
            body=body,
        )

    @staticmethod
    def _json_object(response: BoundedHttpResponse) -> dict[str, Any]:
        if not response.content_type.lower().startswith("application/json"):
            raise OcrError("OCR_RESPONSE_CONTENT_TYPE_INVALID")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise OcrError("OCR_RESPONSE_NOT_JSON") from exc
        if not isinstance(payload, dict):
            raise OcrError("OCR_RESPONSE_INVALID")
        return payload

    @staticmethod
    def _status_code(status: int, fallback: str) -> str:
        return {
            400: "OCR_REQUEST_INVALID",
            401: "OCR_AUTH_FAILED",
            404: "OCR_JOB_NOT_FOUND",
            409: "OCR_JOB_NOT_READY",
            410: "OCR_RESULT_GONE",
            413: "OCR_UPLOAD_TOO_LARGE",
            503: "OCR_UPSTREAM_UNAVAILABLE",
        }.get(status, fallback)
