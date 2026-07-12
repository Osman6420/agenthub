"""Object-store backend behavior (hermetic in-memory backend)."""

from __future__ import annotations

import pytest

from apps.documents import storage


def test_put_get_delete_roundtrip() -> None:
    store = storage.get_object_store()
    key = storage.build_object_key(organization_id=1, document_logical_id="a")
    store.put(key, b"hello", content_type="text/plain")
    assert store.get(key) == b"hello"
    store.delete(key)
    with pytest.raises(storage.StorageError) as exc:
        store.get(key)
    assert exc.value.code == "OBJECT_NOT_FOUND"


def test_delete_is_idempotent() -> None:
    store = storage.get_object_store()
    key = storage.build_object_key(organization_id=2, document_logical_id="a")
    # Deleting a missing key must not raise (purge relies on this for safe retries).
    store.delete(key)


def test_build_object_key_is_tenant_prefixed_unique_and_opaque() -> None:
    a = storage.build_object_key(organization_id=7, document_logical_id="secret-name")
    b = storage.build_object_key(organization_id=7, document_logical_id="secret-name")
    assert a.startswith("tenants/7/documents/")
    assert a != b  # unique per call
    assert "secret-name" not in a  # logical id is not embedded in the key


@pytest.mark.parametrize(
    "bad_key",
    ["", "/tenants/1/x", "other/1/x", "tenants/1/../2/x"],
)
def test_invalid_keys_rejected(bad_key: str) -> None:
    store = storage.get_object_store()
    with pytest.raises(storage.StorageError) as exc:
        store.put(bad_key, b"x", content_type="text/plain")
    assert exc.value.code == "INVALID_OBJECT_KEY"


def test_object_store_is_in_memory_for_tests() -> None:
    # The autouse ``_object_store`` fixture forces the hermetic backend for every gate.
    assert isinstance(storage.get_object_store(), storage.InMemoryObjectStore)
