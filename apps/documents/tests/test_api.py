"""Operator JSON API: authentication, tenant scoping, role gating, redaction."""

from __future__ import annotations

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.documents import services
from apps.documents.models import Document
from apps.documents.tests.conftest import DocFixture

pytestmark = pytest.mark.django_db


def _client(user: object | None) -> Client:
    client = Client()
    if user is not None:
        client.force_login(user)  # type: ignore[arg-type]
    return client


def _upload(client: Client, org_id: int, logical_id: str = "doc-a"):
    return client.post(
        reverse("documents_api:documents"),
        {
            "organization": org_id,
            "logical_id": logical_id,
            "title": "A",
            "file": SimpleUploadedFile("a.txt", b"hello world", content_type="text/plain"),
        },
    )


def test_unauthenticated_is_401(df: DocFixture) -> None:
    resp = _client(None).get(reverse("documents_api:documents"))
    assert resp.status_code == 401


def test_list_is_tenant_scoped(df: DocFixture) -> None:
    services.upload_document(
        organization=df.org,
        logical_id="doc-a",
        title="A",
        mime_type="text/plain",
        data=b"hi",
        actor="op",
    )
    # Author (member of org) sees the document; outsider (other org) sees none.
    resp = _client(df.author).get(reverse("documents_api:documents"))
    assert resp.status_code == 200
    assert [d["logical_id"] for d in resp.json()["documents"]] == ["doc-a"]

    resp_out = _client(df.outsider).get(reverse("documents_api:documents"))
    assert resp_out.json()["documents"] == []


def test_upload_requires_author_role(df: DocFixture) -> None:
    # Auditor (read-only) is denied.
    assert _upload(_client(df.viewer), df.org.id).status_code == 403
    # Scenario editor may upload.
    resp = _upload(_client(df.author), df.org.id)
    assert resp.status_code == 201
    assert resp.json()["version"] == 1


def test_upload_into_out_of_scope_org_is_404(df: DocFixture) -> None:
    # Outsider targeting df.org cannot even see the org.
    assert _upload(_client(df.outsider), df.org.id).status_code == 404


def test_detail_never_exposes_object_key(df: DocFixture) -> None:
    _upload(_client(df.author), df.org.id)
    doc = Document.objects.get(organization=df.org, logical_id="doc-a")
    resp = _client(df.author).get(reverse("documents_api:document_detail", args=[doc.pk]))
    body = resp.json()
    assert resp.status_code == 200
    assert "object_key" not in json.dumps(body)
    assert body["versions"][0]["version"] == 1


def test_cross_tenant_detail_is_404(df: DocFixture) -> None:
    _upload(_client(df.author), df.org.id)
    doc = Document.objects.get(organization=df.org, logical_id="doc-a")
    assert (
        _client(df.outsider)
        .get(reverse("documents_api:document_detail", args=[doc.pk]))
        .status_code
        == 404
    )


def test_soft_delete_requires_author(df: DocFixture) -> None:
    _upload(_client(df.author), df.org.id)
    doc = Document.objects.get(organization=df.org, logical_id="doc-a")
    url = reverse("documents_api:document_detail", args=[doc.pk])
    assert _client(df.viewer).delete(url).status_code == 403
    assert _client(df.author).delete(url).status_code == 200
    doc.refresh_from_db()
    assert doc.is_tombstoned


def test_purge_requires_admin(df: DocFixture) -> None:
    _upload(_client(df.author), df.org.id)
    doc = Document.objects.get(organization=df.org, logical_id="doc-a")
    url = reverse("documents_api:document_purge", args=[doc.pk])
    # Author may not purge; org admin may.
    assert _client(df.author).post(url).status_code == 403
    assert _client(df.admin).post(url).status_code == 200
    assert not Document.objects.filter(pk=doc.pk).exists()


def test_document_set_flow_via_api(df: DocFixture) -> None:
    author = _client(df.author)
    _upload(author, df.org.id)
    doc = Document.objects.get(organization=df.org, logical_id="doc-a")
    version_id = doc.versions.get().pk

    created = author.post(
        reverse("documents_api:document_sets"),
        data=json.dumps({"organization": df.org.id, "logical_id": "set-a", "name": "Set A"}),
        content_type="application/json",
    )
    assert created.status_code == 201
    set_id = created.json()["id"]

    version = author.post(reverse("documents_api:document_set_versions", args=[set_id]))
    assert version.status_code == 201
    set_version_id = version.json()["id"]

    member = author.post(
        reverse("documents_api:set_version_members", args=[set_version_id]),
        data=json.dumps({"document_version_id": version_id}),
        content_type="application/json",
    )
    assert member.status_code == 201

    published = author.post(reverse("documents_api:set_version_publish", args=[set_version_id]))
    assert published.status_code == 200
    assert published.json()["status"] == "promotable"


def test_purge_of_pinned_document_returns_400(df: DocFixture) -> None:
    author = _client(df.author)
    _upload(author, df.org.id)
    doc = Document.objects.get(organization=df.org, logical_id="doc-a")
    doc_set = services.create_document_set(
        organization=df.org, logical_id="set-a", name="Set A", actor="op"
    )
    set_version = services.create_document_set_version(document_set=doc_set, actor="op")
    services.add_document_to_set_version(
        set_version=set_version, document_version=doc.versions.get(), actor="op"
    )
    services.publish_document_set_version(set_version=set_version, actor="op")

    resp = _client(df.admin).post(reverse("documents_api:document_purge", args=[doc.pk]))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "DOCUMENT_IN_USE"
