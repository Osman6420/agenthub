"""Object-store abstraction for document blobs.

Document bytes live in an S3/MinIO object store under a per-tenant key prefix, never in the
database. Two backends implement one narrow interface:

- :class:`S3ObjectStore` — the real boto3 client (used in local/production), reusing the
  bounded-timeout ``settings.OBJECT_STORE`` configuration that ingestion already uses.
- :class:`InMemoryObjectStore` — a hermetic, process-local store so tests and CI exercise the
  full upload/purge flow without a running MinIO (which the suite does not provision).

:func:`get_object_store` selects the backend from ``settings.DOCUMENTS_OBJECT_STORE_BACKEND``.
Keys are always built by :func:`build_object_key` so a caller cannot cross the tenant prefix or
inject traversal segments.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol
from uuid import uuid4

from django.conf import settings


class StorageError(RuntimeError):
    """A safe, content-free storage error carrying a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def build_object_key(*, organization_id: int, document_logical_id: str) -> str:
    """Return an opaque, tenant-prefixed object key.

    The ``tenants/<org_id>/`` prefix is the physical isolation boundary; the random suffix
    makes every version's blob unique. The logical id is *not* embedded (it is not needed to
    locate the blob and would leak naming into the store).
    """
    if organization_id <= 0:
        raise StorageError("INVALID_TENANT")
    return f"tenants/{organization_id}/documents/{uuid4().hex}"


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


def _validate_key(key: str) -> None:
    if not key or not key.startswith("tenants/") or key.startswith("/") or ".." in key.split("/"):
        raise StorageError("INVALID_OBJECT_KEY")


# --- In-memory backend (tests / CI; no external service) --------------------

_MEMORY_LOCK = threading.Lock()
_MEMORY_BLOBS: dict[str, bytes] = {}


def reset_in_memory_store() -> None:
    """Clear the process-local blob store (used by test fixtures for isolation)."""
    with _MEMORY_LOCK:
        _MEMORY_BLOBS.clear()


class InMemoryObjectStore:
    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        _validate_key(key)
        with _MEMORY_LOCK:
            _MEMORY_BLOBS[key] = bytes(data)

    def get(self, key: str) -> bytes:
        _validate_key(key)
        with _MEMORY_LOCK:
            if key not in _MEMORY_BLOBS:
                raise StorageError("OBJECT_NOT_FOUND")
            return _MEMORY_BLOBS[key]

    def delete(self, key: str) -> None:
        _validate_key(key)
        with _MEMORY_LOCK:
            _MEMORY_BLOBS.pop(key, None)


# --- S3 / MinIO backend (local / production) --------------------------------


class S3ObjectStore:
    def _client(self) -> Any:
        import boto3
        from botocore.config import Config

        timeout = int(getattr(settings, "INGESTION_HTTP_TIMEOUT_SECONDS", 15))
        return boto3.client(
            "s3",
            endpoint_url=settings.OBJECT_STORE["endpoint_url"] or None,
            region_name=settings.OBJECT_STORE["region"],
            config=Config(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    @property
    def _bucket(self) -> str:
        return str(settings.OBJECT_STORE["bucket"])

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        _validate_key(key)
        try:
            self._client().put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )
        except Exception as exc:  # noqa: BLE001 — normalize to a stable, content-free code
            raise StorageError("STORAGE_PUT_FAILED") from exc

    def get(self, key: str) -> bytes:
        _validate_key(key)
        cap = int(getattr(settings, "DOCUMENTS_MAX_UPLOAD_BYTES", 25_000_000))
        try:
            response = self._client().get_object(Bucket=self._bucket, Key=key)
            return bytes(response["Body"].read(cap + 1))[:cap]
        except Exception as exc:  # noqa: BLE001
            raise StorageError("STORAGE_GET_FAILED") from exc

    def delete(self, key: str) -> None:
        _validate_key(key)
        try:
            self._client().delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError("STORAGE_DELETE_FAILED") from exc


_BACKENDS: dict[str, type[ObjectStore]] = {
    "memory": InMemoryObjectStore,
    "s3": S3ObjectStore,
}


def get_object_store() -> ObjectStore:
    name = str(getattr(settings, "DOCUMENTS_OBJECT_STORE_BACKEND", "s3"))
    backend = _BACKENDS.get(name)
    if backend is None:
        raise StorageError("STORAGE_BACKEND_UNKNOWN")
    return backend()
