from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from apps.documents import services as document_services
from apps.documents import storage
from apps.ingestion.models import DocumentOcrJob, OcrJobStatus
from apps.ingestion.ocr import AsyncMarkdownOcrClient, OcrError, OcrOutcomeUnknown
from apps.ingestion.ocr_pipeline import parse_image_only_pdf
from apps.ingestion.ocr_services import grant_ocr_profile, register_ocr_profile

JOB_ID = uuid.UUID("4d66bc13-725f-49f2-9a67-997d05d3079e")


class _SecretResolver:
    def resolve(self, ref: str) -> str:
        assert ref == "secret:ocr-key"
        return "token"  # noqa: S105


class _Response:
    def __init__(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.status = status
        self.body = body
        self.content_type = content_type

    def read(self, amount: int) -> bytes:
        return self.body[:amount]

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.content_type if name.lower() == "content-type" else default


class _Connection:
    def __init__(self, response: _Response, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.requests: list[tuple[Any, ...]] = []

    def request(
        self, method: str, url: str, body: bytes | None = None, headers: Any = None
    ) -> None:
        self.requests.append((method, url, body, headers))
        if self.error:
            raise self.error

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        pass


class _Factory:
    def __init__(self, *connections: _Connection) -> None:
        self.connections = list(connections)
        self.used: list[_Connection] = []

    def __call__(self, ip: str, port: int, timeout: float, hostname: str) -> _Connection:
        assert (ip, port, hostname) == ("93.184.216.34", 443, "ocr.example.com")
        connection = self.connections.pop(0)
        self.used.append(connection)
        return connection


def _resolver(host: str, port: int) -> list[tuple[Any, ...]]:
    return [(2, 1, 6, "", ("93.184.216.34", port))]


def _profile(**overrides: Any) -> Any:
    values = {
        "scheme": "https",
        "host": "ocr.example.com",
        "port": 443,
        "base_path": "/api/v1",
        "secret_ref": "secret:ocr-key",
        "timeout_seconds": 30,
        "poll_interval_seconds": 2,
        "max_poll_attempts": 4,
        "max_upload_bytes": 52_428_800,
        "max_pages": 500,
        "max_result_bytes": 1_000_000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _client(factory: _Factory, sleeper=lambda seconds: None) -> AsyncMarkdownOcrClient:
    return AsyncMarkdownOcrClient(
        resolver=_resolver,
        connection_factory=factory,
        secret_resolver=_SecretResolver(),
        sleeper=sleeper,
    )


def test_contract_flow_multipart_poll_markdown_and_ack() -> None:
    submit = _Connection(
        _Response(
            202,
            (
                f'{{"job_id":"{JOB_ID}","status":"QUEUED",'
                f'"status_url":"https://attacker.example/ocr-jobs/{JOB_ID}",'
                '"created_at":"2026-07-13T12:00:00+03:00"}'
            ).encode(),
        )
    )
    queued = _Connection(_Response(200, f'{{"job_id":"{JOB_ID}","status":"QUEUED"}}'.encode()))
    success = _Connection(_Response(200, f'{{"job_id":"{JOB_ID}","status":"SUCCEEDED"}}'.encode()))
    result = _Connection(_Response(200, b"# title\n\nOCR text", "text/markdown; charset=utf-8"))
    ack = _Connection(_Response(204, b"", ""))
    factory = _Factory(submit, queued, success, result, ack)
    sleeps: list[float] = []
    client = _client(factory, sleeps.append)

    assert client.submit(_profile(), b"%PDF") == JOB_ID
    method, path, body, headers = submit.requests[0]
    assert method == "POST" and path == "/api/v1/ocr-jobs"
    assert body.count(b"Content-Disposition: form-data;") == 1
    assert body.count(b'name="file"; filename="document.pdf"') == 1
    assert headers["Authorization"] == "Bearer token"
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=agenthub-")
    client.wait_for_success(_profile(), JOB_ID)
    assert sleeps == [2.0]
    # Service-provided URLs are data, never egress destinations.
    # Poll/result paths are profile-based.
    assert queued.requests[0][1] == f"/api/v1/ocr-jobs/{JOB_ID}"
    assert client.download(_profile(), JOB_ID).startswith(b"# title")
    assert result.requests[0][1] == f"/api/v1/ocr-jobs/{JOB_ID}/result"
    client.acknowledge(_profile(), JOB_ID)
    assert ack.requests[0][0:3] == ("POST", f"/api/v1/ocr-jobs/{JOB_ID}/ack", b"")


def test_submit_timeout_is_outcome_unknown_and_not_retried() -> None:
    factory = _Factory(_Connection(_Response(202, b"{}"), TimeoutError()))
    with pytest.raises(OcrOutcomeUnknown, match="OCR_SUBMIT_OUTCOME_UNKNOWN"):
        _client(factory).submit(_profile(), b"%PDF")
    assert len(factory.used) == 1


def test_private_dns_and_redirect_fail_closed() -> None:
    private_client = AsyncMarkdownOcrClient(
        resolver=lambda host, port: [(2, 1, 6, "", ("127.0.0.1", port))],
        connection_factory=_Factory(),
        secret_resolver=_SecretResolver(),
    )
    with pytest.raises(OcrError, match="DESTINATION_NOT_PUBLIC"):
        private_client.submit(_profile(), b"%PDF")
    with pytest.raises(OcrError, match="REDIRECT_NOT_ALLOWED"):
        _client(_Factory(_Connection(_Response(302, b"")))).submit(_profile(), b"%PDF")


def test_response_and_result_are_bounded_and_validated() -> None:
    with pytest.raises(OcrError, match="OCR_RESPONSE_NOT_JSON"):
        _client(_Factory(_Connection(_Response(202, b"not-json")))).submit(_profile(), b"%PDF")
    with pytest.raises(OcrError, match="OCR_RESULT_CONTENT_TYPE_INVALID"):
        _client(_Factory(_Connection(_Response(200, b"{}", "application/json")))).download(
            _profile(), JOB_ID
        )


def test_failed_job_exposes_only_sanitized_error_code() -> None:
    response = _Connection(
        _Response(
            200,
            f'{{"job_id":"{JOB_ID}","status":"FAILED","error_code":"OCR_ENGINE_DOWN"}}'.encode(),
        )
    )
    with pytest.raises(OcrError, match="OCR_JOB_FAILED") as exc:
        _client(_Factory(response)).wait_for_success(_profile(), JOB_ID)
    assert exc.value.upstream_code == "OCR_ENGINE_DOWN"


@pytest.mark.parametrize("status", ["ACKNOWLEDGED", "EXPIRED"])
def test_terminal_status_without_download_fails_closed(status: str) -> None:
    response = _Connection(_Response(200, f'{{"job_id":"{JOB_ID}","status":"{status}"}}'.encode()))
    with pytest.raises(OcrError, match=f"OCR_JOB_{status}"):
        _client(_Factory(response)).wait_for_success(_profile(), JOB_ID)


def test_ack_retries_transient_503_then_accepts_204() -> None:
    unavailable = _Connection(
        _Response(
            503,
            b'{"error":{"code":"OBJECT_STORE_UNAVAILABLE","message":"temporary"}}',
        )
    )
    success = _Connection(_Response(204, b"", ""))
    factory = _Factory(unavailable, success)

    _client(factory).acknowledge(_profile(), JOB_ID)

    assert len(factory.used) == 2


def test_ack_result_gone_is_terminal_not_success() -> None:
    gone = _Connection(_Response(410, b'{"error":{"code":"RESULT_GONE","message":"gone"}}'))

    with pytest.raises(OcrError, match="OCR_RESULT_GONE"):
        _client(_Factory(gone)).acknowledge(_profile(), JOB_ID)


def _blank_pdf() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 5\n0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n"
    return bytes(pdf + str(xref).encode() + b"\n%%EOF")


@pytest.fixture(autouse=True)
def _memory_store(settings: Any) -> Iterator[None]:
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
    storage.reset_in_memory_store()
    yield
    storage.reset_in_memory_store()


class _PipelineClient:
    def submit(self, profile: Any, pdf: bytes) -> uuid.UUID:
        return JOB_ID

    def wait_for_success(self, profile: Any, job_id: uuid.UUID) -> None:
        pass

    def download(self, profile: Any, job_id: uuid.UUID) -> bytes:
        return b"# OCR\n\nPersisted markdown"

    def acknowledge(self, profile: Any, job_id: uuid.UUID) -> None:
        job = DocumentOcrJob.objects.get(job_id=job_id)
        assert job.status == OcrJobStatus.RESULT_PERSISTED
        assert storage.get_object_store().get(job.result_object_key).startswith(b"# OCR")


@pytest.mark.django_db
def test_pipeline_persists_result_before_ack_and_reuses_it() -> None:
    from apps.audit.models import AuditEvent
    from apps.tenancy.models import Organization

    org = Organization.objects.create(slug="ocr", name="OCR")
    admin = get_user_model().objects.create_superuser(username="platform", password=None)
    profile = register_ocr_profile(
        actor=admin,
        logical_id="ocr",
        revision=1,
        provider="async_markdown_ocr",
        scheme="https",
        host="ocr.example.com",
        port=443,
        base_path="/api/v1",
        secret_ref="secret:ocr-key",  # noqa: S106
        timeout_seconds=30,
        poll_interval_seconds=2,
        max_poll_attempts=10,
        max_upload_bytes=52_428_800,
        max_pages=500,
        max_result_bytes=1_000_000,
    )
    grant_ocr_profile(actor=admin, organization=org, ocr_profile=profile)
    profile_audit = AuditEvent.objects.get(action="ocr_profile.create", outcome="success")
    assert "ocr.example.com" not in str(profile_audit.after)
    assert "ocr-key" not in str(profile_audit.after)
    document_set = document_services.create_document_set(
        organization=org, logical_id="scans", name="Scans", actor="operator"
    )
    draft = document_services.create_document_set_version(
        document_set=document_set, actor="operator"
    )
    version = document_services.upload_document(
        organization=org,
        logical_id="scan",
        title="Scan",
        mime_type="application/pdf",
        data=_blank_pdf(),
        actor="operator",
        document_set_version=draft,
    )
    parsed = parse_image_only_pdf(
        document_version=version,
        pdf=_blank_pdf(),
        ocr_profile=profile,
        actor="worker",
        client=_PipelineClient(),  # type: ignore[arg-type]
    )
    assert parsed.parser == "external_ocr" and "Persisted markdown" in parsed.text
    job = DocumentOcrJob.objects.get()
    assert job.status == OcrJobStatus.ACKNOWLEDGED
    result_key = job.result_object_key
    document_services.soft_delete_document(version.document, actor="operator")
    version.memberships.all().delete()
    document_services.purge_document(version.document, actor="platform")
    with pytest.raises(storage.StorageError, match="OBJECT_NOT_FOUND"):
        storage.get_object_store().get(result_key)

    other = Organization.objects.create(slug="other", name="Other")
    other_set = document_services.create_document_set(
        organization=other, logical_id="scans", name="Scans", actor="operator"
    )
    other_draft = document_services.create_document_set_version(
        document_set=other_set, actor="operator"
    )
    other_version = document_services.upload_document(
        organization=other,
        logical_id="scan",
        title="Scan",
        mime_type="application/pdf",
        data=_blank_pdf(),
        actor="operator",
        document_set_version=other_draft,
    )
    with pytest.raises(OcrError, match="OCR_PROFILE_NOT_GRANTED"):
        parse_image_only_pdf(
            document_version=other_version,
            pdf=_blank_pdf(),
            ocr_profile=profile,
            actor="worker",
            client=_PipelineClient(),  # type: ignore[arg-type]
        )
    profile.host = "changed.example.com"
    with pytest.raises(ValueError, match="immutable"):
        profile.save()


@pytest.mark.django_db
def test_profile_registration_is_platform_admin_only_and_audit_redacts_endpoint() -> None:
    from apps.audit.models import AuditEvent

    user = get_user_model().objects.create_user(username="ordinary")
    fields = {
        "logical_id": "ocr",
        "revision": 1,
        "provider": "async_markdown_ocr",
        "scheme": "https",
        "host": "ocr.example.com",
        "port": 443,
        "base_path": "/api/v1",
        "secret_ref": "secret:very-sensitive",  # noqa: S106
        "timeout_seconds": 30,
        "poll_interval_seconds": 2,
        "max_poll_attempts": 10,
        "max_upload_bytes": 52_428_800,
        "max_pages": 500,
        "max_result_bytes": 1_000_000,
    }
    with pytest.raises(PermissionError):
        register_ocr_profile(actor=user, **fields)
    audit = AuditEvent.objects.get(action="ocr_profile.create")
    assert "very-sensitive" not in str(audit.after) + audit.reason
