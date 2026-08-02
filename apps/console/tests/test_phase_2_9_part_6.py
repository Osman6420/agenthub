"""Phase 2.9 Part 6 navigation and governed document-content access."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.builder.models import WorkflowDraft
from apps.catalog.models import AIProject, Scenario
from apps.console.forms import BindingForm
from apps.documents import services, storage
from apps.documents.content_access import DocumentContentError, read_document_version_content
from apps.documents.models import DocumentSet, DocumentSetVersionStatus
from apps.identity.capabilities import Capability
from apps.identity.models import (
    Consumer,
    ConsumerProtocol,
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


@override_settings(AI_AUTHORING_MODEL_PROFILE_ID=None, AI_AUTHORING_PROVIDER="")
def test_missing_ai_authoring_profile_is_not_reported_as_invalid() -> None:
    from apps.console.views import _ai_authoring_preflight

    result = _ai_authoring_preflight()

    assert result["available"] is False
    assert "profile ID" in str(result["message"])
    assert "profile ayar" not in str(result["message"])


@pytest.fixture(autouse=True)
def _memory_store(settings: Any) -> Iterator[None]:
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
    storage.reset_in_memory_store()
    yield
    storage.reset_in_memory_store()


def _member(username: str, organization: Organization) -> tuple[Any, OrganizationMembership]:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=organization, user=user)
    return user, membership


def _document_fixture() -> tuple[Organization, DocumentSet, Any]:
    organization = Organization.objects.create(slug="content-org", name="Content org")
    document_set = DocumentSet.objects.create(
        organization=organization,
        logical_id="policies",
        name="Policies",
    )
    draft = services.get_or_create_manual_draft(document_set=document_set, actor="seed")
    version = services.upload_document(
        organization=organization,
        logical_id="returns",
        title="Return policy",
        mime_type="text/plain",
        data=b"<script>alert('x')</script>\nThirty days.",
        actor="seed",
        document_set_version=draft,
    )
    return organization, document_set, version


def _set_duty(
    *,
    user: Any,
    membership: OrganizationMembership,
    document_set: DocumentSet,
    responsibility: str,
) -> None:
    DocumentSetResponsibilityAssignment.objects.create(
        organization=document_set.organization,
        membership=membership,
        document_set=document_set,
        responsibility=responsibility,
        assigned_by=user,
    )


@pytest.mark.django_db
def test_navigation_follows_exact_responsibilities_even_when_runs_are_empty(
    client: Client,
) -> None:
    organization = Organization.objects.create(slug="nav-org", name="Navigation org")
    project = AIProject.objects.create(organization=organization, slug="p", name="Project")
    scenario = Scenario.objects.create(
        organization=organization,
        project=project,
        slug="s",
        name="Scenario",
    )
    document_set = DocumentSet.objects.create(
        organization=organization,
        logical_id="docs",
        name="Documents",
    )

    editor, editor_membership = _member("editor-nav", organization)
    ScenarioResponsibilityAssignment.objects.create(
        organization=organization,
        membership=editor_membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=editor,
    )
    client.force_login(editor)
    editor_body = client.get(reverse("console:dashboard")).content.decode()
    assert f'href="{reverse("console:projects")}"' in editor_body
    assert f'href="{reverse("console:runs")}"' not in editor_body
    assert f'href="{reverse("console:documents")}"' not in editor_body

    runtime, runtime_membership = _member("runtime-nav", organization)
    ScenarioResponsibilityAssignment.objects.create(
        organization=organization,
        membership=runtime_membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.RUNTIME_OPERATOR,
        assigned_by=runtime,
    )
    client.force_login(runtime)
    runtime_body = client.get(reverse("console:dashboard")).content.decode()
    assert f'href="{reverse("console:projects")}"' in runtime_body
    assert f'href="{reverse("console:runs")}"' in runtime_body

    reader, reader_membership = _member("reader-nav", organization)
    _set_duty(
        user=reader,
        membership=reader_membership,
        document_set=document_set,
        responsibility=DocumentSetResponsibility.CONTENT_READER,
    )
    client.force_login(reader)
    reader_body = client.get(reverse("console:dashboard")).content.decode()
    assert f'href="{reverse("console:documents")}"' in reader_body
    assert f'href="{reverse("console:projects")}"' not in reader_body
    assert f'href="{reverse("console:runs")}"' not in reader_body
    documents_body = client.get(reverse("console:documents")).content.decode()
    assert "organization_admin" in documents_body
    assert "scenario_editor" not in documents_body

    unassigned, _ = _member("unassigned-nav", organization)
    client.force_login(unassigned)
    unassigned_body = client.get(reverse("console:dashboard")).content.decode()
    assert f'href="{reverse("console:projects")}"' not in unassigned_body
    assert f'href="{reverse("console:documents")}"' not in unassigned_body
    assert f'href="{reverse("console:runs")}"' not in unassigned_body


@pytest.mark.django_db
def test_local_console_not_found_has_safe_guidance_without_route_dump(client: Client) -> None:
    organization = Organization.objects.create(slug="error-org", name="Error org")
    user, _ = _member("error-user", organization)
    client.force_login(user)

    response = client.get("/console/does-not-exist/")

    assert response.status_code == 404
    body = response.content.decode()
    assert "Bu sayfa kullanılamıyor" in body
    assert "URL patterns" not in body
    assert "Traceback" not in body
    assert response.headers["Cache-Control"] == "private, no-store"

    client.logout()
    anonymous = client.get("/console/still-does-not-exist/")
    assert anonymous.status_code == 404
    assert "URL patterns" not in anonymous.content.decode()


@pytest.mark.django_db
def test_content_reader_gets_escaped_preview_and_attachment_download(client: Client) -> None:
    organization, document_set, version = _document_fixture()
    reader, membership = _member("content-reader", organization)
    _set_duty(
        user=reader,
        membership=membership,
        document_set=document_set,
        responsibility=DocumentSetResponsibility.CONTENT_READER,
    )
    client.force_login(reader)
    args = [document_set.public_id, version.document.public_id, version.pk]

    detail = client.get(
        reverse(
            "console:document_set_document_detail",
            args=[document_set.public_id, version.document.public_id],
        )
    )
    assert detail.status_code == 200
    assert reverse("console:document_version_preview", args=args) in detail.content.decode()

    preview = client.get(reverse("console:document_version_preview", args=args))
    assert preview.status_code == 200
    assert b"&lt;script&gt;alert" in preview.content
    assert b"<script>alert" not in preview.content
    assert preview.headers["Cache-Control"] == "private, no-store"
    assert preview.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in preview.headers["Content-Security-Policy"]

    download = client.get(reverse("console:document_version_download", args=args))
    assert download.status_code == 200
    assert download.content == b"<script>alert('x')</script>\nThirty days."
    assert download.headers["Content-Type"] == "application/octet-stream"
    assert download.headers["Content-Disposition"].startswith("attachment;")
    assert download.headers["Cache-Control"] == "private, no-store"

    events = AuditEvent.objects.filter(action__startswith="document_content.")
    assert events.filter(action="document_content.preview", outcome="success").exists()
    assert events.filter(action="document_content.download", outcome="success").exists()
    serialized = json.dumps(list(events.values("reason", "before", "after")))
    assert "<script>" not in serialized
    assert version.object_key not in serialized


@pytest.mark.django_db
def test_metadata_viewer_cannot_read_bytes_and_denial_is_audited() -> None:
    organization, document_set, version = _document_fixture()
    viewer, membership = _member("metadata-viewer", organization)
    _set_duty(
        user=viewer,
        membership=membership,
        document_set=document_set,
        responsibility=DocumentSetResponsibility.METADATA_VIEWER,
    )

    with pytest.raises(DocumentContentError, match="DOCUMENT_CONTENT_FORBIDDEN"):
        read_document_version_content(
            actor=viewer,
            document_set=document_set,
            document=version.document,
            version=version,
            operation="download",
            max_bytes=25_000_000,
        )

    event = AuditEvent.objects.get(action="document_content.download", outcome="deny")
    assert event.reason == "DOCUMENT_CONTENT_FORBIDDEN"
    assert version.object_key not in json.dumps(event.after)


@pytest.mark.django_db
def test_content_routes_hide_same_tenant_other_set_and_cross_tenant_parents(
    client: Client,
) -> None:
    organization, allowed_set, _ = _document_fixture()
    reader, membership = _member("scope-reader", organization)
    _set_duty(
        user=reader,
        membership=membership,
        document_set=allowed_set,
        responsibility=DocumentSetResponsibility.CONTENT_READER,
    )
    other_set = DocumentSet.objects.create(
        organization=organization,
        logical_id="other-set",
        name="Other set",
    )
    other_draft = services.get_or_create_manual_draft(document_set=other_set, actor="seed")
    other_version = services.upload_document(
        organization=organization,
        logical_id="other-document",
        title="Other document",
        mime_type="text/plain",
        data=b"same tenant but other exact set",
        actor="seed",
        document_set_version=other_draft,
    )
    foreign_org = Organization.objects.create(slug="foreign-content", name="Foreign content")
    foreign_set = DocumentSet.objects.create(
        organization=foreign_org,
        logical_id="foreign-set",
        name="Foreign set",
    )
    foreign_draft = services.get_or_create_manual_draft(document_set=foreign_set, actor="seed")
    foreign_version = services.upload_document(
        organization=foreign_org,
        logical_id="foreign-document",
        title="Foreign document",
        mime_type="text/plain",
        data=b"foreign tenant",
        actor="seed",
        document_set_version=foreign_draft,
    )
    client.force_login(reader)

    same_tenant_probe = client.get(
        reverse(
            "console:document_version_download",
            args=[allowed_set.public_id, other_version.document.public_id, other_version.pk],
        )
    )
    foreign_probe = client.get(
        reverse(
            "console:document_version_download",
            args=[foreign_set.public_id, foreign_version.document.public_id, foreign_version.pk],
        )
    )

    assert same_tenant_probe.status_code == 404
    assert foreign_probe.status_code == 404
    assert not AuditEvent.objects.filter(action="document_content.download").exists()


@pytest.mark.django_db
def test_content_access_rejects_unpinned_version_and_unsafe_inline_type(client: Client) -> None:
    organization, document_set, pinned = _document_fixture()
    document_set.versions.filter(status=DocumentSetVersionStatus.DRAFT).update(
        status=DocumentSetVersionStatus.PROMOTABLE
    )
    draft = services.get_or_create_manual_draft(document_set=document_set, actor="seed")
    unpinned = services.upload_document(
        organization=organization,
        logical_id="returns",
        title="Return policy",
        mime_type="text/plain",
        data=b"new version",
        actor="seed",
        document_set_version=draft,
    )
    # Remove only the new exact pin while retaining the document's earlier set membership.
    draft.memberships.filter(document_version=unpinned).delete()
    reader, membership = _member("bounded-reader", organization)
    _set_duty(
        user=reader,
        membership=membership,
        document_set=document_set,
        responsibility=DocumentSetResponsibility.CONTENT_READER,
    )
    client.force_login(reader)

    unpinned_url = reverse(
        "console:document_version_preview",
        args=[document_set.public_id, pinned.document.public_id, unpinned.pk],
    )
    assert client.get(unpinned_url).status_code == 403

    pinned.mime_type = "text/html"
    pinned.save(update_fields=["mime_type"])
    args = [document_set.public_id, pinned.document.public_id, pinned.pk]
    preview = client.get(reverse("console:document_version_preview", args=args))
    assert preview.status_code == 422
    assert b"CONTENT_PREVIEW_TYPE_UNSUPPORTED" in preview.content
    assert preview.headers["Cache-Control"] == "private, no-store"
    download = client.get(reverse("console:document_version_download", args=args))
    assert download.status_code == 200
    assert download.headers["Content-Type"] == "application/octet-stream"
    assert download.headers["Content-Disposition"].startswith("attachment;")


@pytest.mark.django_db
def test_oversized_preview_stops_before_storage_and_audit_failure_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, document_set, version = _document_fixture()
    reader, membership = _member("fail-closed-reader", organization)
    _set_duty(
        user=reader,
        membership=membership,
        document_set=document_set,
        responsibility=DocumentSetResponsibility.CONTENT_READER,
    )

    class BombStore:
        def get(self, key: str) -> bytes:
            raise AssertionError(f"storage must not be read: {key}")

    monkeypatch.setattr("apps.documents.content_access.get_object_store", lambda: BombStore())
    version.byte_size = 262_145
    version.save(update_fields=["byte_size"])
    with pytest.raises(DocumentContentError, match="CONTENT_TOO_LARGE"):
        read_document_version_content(
            actor=reader,
            document_set=document_set,
            document=version.document,
            version=version,
            operation="preview",
            max_bytes=262_144,
            allowed_mime_types=frozenset({"text/plain"}),
            require_utf8=True,
        )

    version.byte_size = len(b"<script>alert('x')</script>\nThirty days.")
    version.save(update_fields=["byte_size"])
    monkeypatch.setattr("apps.documents.content_access.get_object_store", storage.get_object_store)
    monkeypatch.setattr(
        "apps.documents.content_access.record_event",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        read_document_version_content(
            actor=reader,
            document_set=document_set,
            document=version.document,
            version=version,
            operation="download",
            max_bytes=25_000_000,
        )


@pytest.mark.django_db
def test_minimum_manifest_preset_is_scenario_owned_latest_and_recommendation_only(
    client: Client,
) -> None:
    organization = Organization.objects.create(slug="preset-org", name="Preset org")
    project = AIProject.objects.create(organization=organization, slug="p", name="Project")
    scenario = Scenario.objects.create(project=project, slug="s", name="Scenario")
    manager, membership = _member("release-preset", organization)
    ScenarioResponsibilityAssignment.objects.create(
        organization=organization,
        membership=membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.RELEASE_MANAGER,
        assigned_by=manager,
    )
    WorkflowDraft.objects.create(
        organization=organization,
        project=project,
        scenario=scenario,
        name="Flow",
        logical_id="scenario-flow",
        body={},
        created_by="seed",
        updated_by="seed",
    )
    for version in (1, 2):
        ArtifactVersion.objects.create(
            organization=organization,
            type=ArtifactType.WORKFLOW_DEFINITION,
            logical_id="scenario-flow",
            version=version,
            body={},
            checksum=str(version) * 64,
            created_by="seed",
        )
    input_artifact = ArtifactVersion.objects.create(
        organization=organization,
        type=ArtifactType.INPUT_CONTRACT,
        logical_id=f"scenario-{scenario.public_id.hex}-input_contract",
        version=1,
        body={},
        checksum="a" * 64,
        created_by="seed",
    )
    ArtifactVersion.objects.create(
        organization=organization,
        type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="unrelated-output",
        version=9,
        body={},
        checksum="b" * 64,
        created_by="seed",
    )
    client.force_login(manager)

    response = client.get(
        reverse("console:scenario_artifact_options", args=[scenario.public_id]),
        {"preset": "minimum"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["level"] == "preset"
    assert payload["recommendation_only"] is True
    by_role = {item["role"]: item for item in payload["options"]}
    assert by_role["workflow_definition"]["version"] == 2
    assert by_role["input_contract"]["artifact_version_id"] == input_artifact.pk
    assert "output_contract" in payload["missing_roles"]
    assert "eval_suite" in payload["missing_roles"]
    assert all(item["logicalId"] != "unrelated-output" for item in payload["options"])


@pytest.mark.django_db
def test_capability_preset_requires_exact_reviewed_allowlist() -> None:
    organization = Organization.objects.create(slug="binding-org", name="Binding org")
    project = AIProject.objects.create(organization=organization, slug="p", name="Project")
    scenario = Scenario.objects.create(project=project, slug="s", name="Scenario")
    admin, membership = _member("binding-admin", organization)
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=admin,
    )
    consumer = Consumer.objects.create(
        organization=organization,
        subject="svc:binding",
        name="Binding service",
        protocol=ConsumerProtocol.REST,
    )
    valid = BindingForm(
        data={
            "consumer": consumer.pk,
            "scenario": scenario.pk,
            "status": "active",
            "capability_preset": "rag_debug_reader",
            "capabilities": [Capability.WORKFLOW_RUN, Capability.RETRIEVE_DEBUG],
        },
        user=admin,
    )
    assert valid.is_valid(), valid.errors
    assert set(valid.save(commit=False).capabilities) == {
        Capability.WORKFLOW_RUN,
        Capability.RETRIEVE_DEBUG,
    }

    forged = BindingForm(
        data={
            "consumer": consumer.pk,
            "scenario": scenario.pk,
            "status": "active",
            "capability_preset": "workflow_runner",
            "capabilities": [Capability.WORKFLOW_RUN, Capability.RELEASE_PROMOTE],
        },
        user=admin,
    )
    assert not forged.is_valid()
    assert "Özel seçim" in forged.errors["capabilities"][0]
