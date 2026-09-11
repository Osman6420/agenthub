"""Console document-set lifecycle UI tests (Phase 2 · P8.2).

Create a set, open a draft version, add a member, publish — role/tenant-scoped, over the audited
``apps.documents.services``. Hermetic in-memory object store (uploads need no MinIO).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.documents import storage
from apps.documents.models import (
    DocumentSet,
    DocumentSetVersion,
    DocumentSetVersionStatus,
)
from apps.documents.services import (
    create_document_set,
    create_document_set_version,
    upload_document,
)
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
)
from apps.identity.roles import Role
from apps.ingestion.job_lifecycle import create_build_job
from apps.ingestion.tests.test_staged_build import _granted_profile, _published_set_version
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


@pytest.fixture(autouse=True)
def _memory_store(settings: Any) -> Iterator[None]:
    settings.DOCUMENTS_OBJECT_STORE_BACKEND = "memory"
    storage.reset_in_memory_store()
    yield
    storage.reset_in_memory_store()


def _member(username: str, org: Organization, role: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    if role == Role.ORGANIZATION_ADMIN:
        OrganizationResponsibilityAssignment.objects.create(
            organization=org,
            membership=membership,
            responsibility=OrganizationResponsibility.ADMINISTRATOR,
            assigned_by=user,
        )
    elif role == Role.AUDITOR:
        OrganizationResponsibilityAssignment.objects.create(
            organization=org,
            membership=membership,
            responsibility=OrganizationResponsibility.AUDITOR,
            assigned_by=user,
        )
    elif role == Role.PROJECT_OWNER:
        for document_set in org.document_sets.all():
            DocumentSetResponsibilityAssignment.objects.create(
                organization=org,
                membership=membership,
                document_set=document_set,
                responsibility=DocumentSetResponsibility.MANAGER,
                assigned_by=user,
            )
    return user


@pytest.mark.django_db
def test_organization_admin_can_create_document_set(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    client.force_login(_member("owner", org, Role.ORGANIZATION_ADMIN))

    response = client.post(
        reverse("console:document_set_create"),
        {"organization": org.id, "logical_id": "kb", "name": "Knowledge base"},
    )
    assert response.status_code == 302
    document_set = DocumentSet.objects.get(organization=org)
    assert document_set.logical_id.startswith("knowledge-base-")


@pytest.mark.django_db
def test_existing_document_add_requires_source_content_access(client: Client) -> None:
    org = Organization.objects.create(slug="private-docs", name="Private docs")
    target = create_document_set(organization=org, logical_id="target", name="Target", actor="seed")
    draft = create_document_set_version(document_set=target, actor="seed")
    manager = _member("target-manager", org, Role.PROJECT_OWNER)
    private = create_document_set(
        organization=org, logical_id="private", name="Private", actor="seed"
    )
    private_draft = create_document_set_version(document_set=private, actor="seed")
    upload_document(
        organization=org,
        logical_id="private-document",
        title="Confidential title",
        mime_type="text/plain",
        data=b"private",
        actor="seed",
        document_set_version=private_draft,
    )
    document = private_draft.memberships.get().document_version.document
    client.force_login(manager)
    detail_url = reverse("console:document_set_detail_public", args=[target.public_id])
    add_url = reverse("console:document_set_add_member", args=[draft.pk])
    response = client.get(detail_url)
    assert response.status_code == 200
    assert response.context["candidate_docs"] == []
    assert document.logical_id not in response.content.decode()
    assert client.post(add_url, {"document_id": document.pk}).status_code == 302
    assert not draft.memberships.exists()
    for invalid_id in ("9" * 20, "²", "not-an-id"):
        assert client.post(add_url, {"document_id": invalid_id}).status_code == 302
    assert not draft.memberships.exists()
    assert AuditEvent.objects.filter(
        action="documents.set_version.add_member",
        outcome="deny",
        reason="DOCUMENT_NOT_READABLE",
    ).exists()
    DocumentSetResponsibilityAssignment.objects.create(
        organization=org,
        membership=OrganizationMembership.objects.get(user=manager),
        document_set=private,
        responsibility=DocumentSetResponsibility.CONTENT_READER,
        assigned_by=manager,
    )
    response = client.get(detail_url)
    assert [d["id"] for d in response.context["candidate_docs"]] == [document.pk]
    assert client.post(add_url, {"document_id": document.pk}).status_code == 302
    assert draft.memberships.get().document_version.document_id == document.pk
    document_url = reverse(
        "console:document_set_document_detail", args=[target.public_id, document.public_id]
    )
    assert document_url in client.get(detail_url).content.decode()
    viewer = _member("target-metadata-viewer", org, Role.AUDITOR)
    DocumentSetResponsibilityAssignment.objects.create(
        organization=org,
        membership=OrganizationMembership.objects.get(user=viewer),
        document_set=target,
        responsibility=DocumentSetResponsibility.METADATA_VIEWER,
        assigned_by=manager,
    )
    client.force_login(viewer)
    rendered = client.get(detail_url).content.decode()
    assert document.title in rendered
    assert document_url not in rendered
    assert client.get(document_url).status_code == 404


@pytest.mark.django_db
def test_document_detail_pages_preserve_totals_and_selected_version(client: Client) -> None:
    org = Organization.objects.create(slug="paged-docs", name="Paged docs")
    docset = create_document_set(organization=org, logical_id="paged", name="Paged", actor="seed")
    draft = create_document_set_version(document_set=docset, actor="seed")
    for ordinal in range(27):
        upload_document(
            organization=org,
            logical_id=f"doc-{ordinal:02}",
            title=f"Document {ordinal:02}",
            mime_type="text/plain",
            data=b"page",
            actor="seed",
            document_set_version=draft,
        )
    for version in range(2, 24):
        DocumentSetVersion.objects.create(
            organization=org,
            document_set=docset,
            version=version,
            status="promotable",
        )
    client.force_login(_member("paged-manager", org, Role.PROJECT_OWNER))
    url = reverse("console:document_set_detail_public", args=[docset.public_id])
    response = client.get(url, {"version": draft.pk})
    assert response.status_code == 200
    current = response.context["current_version"]
    assert current["id"] == draft.pk
    assert current["member_total"] == 27
    assert len(current["members"]) == 25
    assert len(response.context["other_versions"]) == 20
    assert response.context["history_page"].paginator.count == 22
    response = client.get(url, {"version": draft.pk, "member_page": 2, "history_page": 2})
    assert len(response.context["current_version"]["members"]) == 2
    assert len(response.context["other_versions"]) == 2
    assert "27 doküman sürümü" in response.content.decode()
    response = client.get(url, {"version": str(draft.pk), "member_q": "Document 26"})
    assert response.context["current_version"]["member_total"] == 27
    assert [m["logical_id"] for m in response.context["current_version"]["members"]] == ["doc-26"]
    response = client.get(url, {"version": str(draft.pk), "member_q": "no matching document"})
    assert "Aramanızla eşleşen doküman bulunamadı." in response.content.decode()
    for invalid_id in ("9" * 20, "²", "not-an-id"):
        response = client.get(url, {"version": invalid_id})
        assert response.status_code == 200
        assert response.context["current_version"]["version"] == 23


@pytest.mark.django_db
def test_full_set_version_lifecycle(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    draft = create_document_set_version(document_set=document_set, actor="seed")
    upload_document(
        organization=org,
        logical_id="doc-1",
        title="Doc 1",
        mime_type="text/plain",
        data=b"hello",
        actor="seed",
        document_set_version=draft,
    )
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))

    # 1. upload atomically opened and populated the exact draft version
    version = DocumentSetVersion.objects.get(document_set=document_set)
    assert version.status == DocumentSetVersionStatus.DRAFT

    # 2. add a member (pins the document's current version)
    from apps.documents.models import Document

    document = Document.objects.get(organization=org, logical_id="doc-1")
    client.post(
        reverse("console:document_set_add_member", args=[version.id]),
        {"document_id": document.id},
    )
    assert version.memberships.count() == 1

    # 3. publish → promotable
    client.post(reverse("console:document_set_version_publish", args=[version.id]))
    version.refresh_from_db()
    assert version.status == DocumentSetVersionStatus.PROMOTABLE


@pytest.mark.django_db
def test_publish_empty_version_fails_gracefully(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))
    client.post(reverse("console:document_set_version_create", args=[document_set.id]))
    version = DocumentSetVersion.objects.get(document_set=document_set)

    response = client.post(reverse("console:document_set_version_publish", args=[version.id]))
    assert response.status_code == 302  # redirected with an error, not a 500
    version.refresh_from_db()
    assert version.status == DocumentSetVersionStatus.DRAFT  # unchanged (SET_VERSION_EMPTY)


@pytest.mark.django_db
def test_cross_tenant_set_detail_is_not_found(client: Client) -> None:
    org_a = Organization.objects.create(slug="org-a", name="A")
    org_b = Organization.objects.create(slug="org-b", name="B")
    set_b = create_document_set(organization=org_b, logical_id="kb-b", name="B", actor="seed")
    client.force_login(_member("owner-a", org_a, Role.PROJECT_OWNER))

    assert client.get(reverse("console:document_set_detail", args=[set_b.id])).status_code == 404


@pytest.mark.django_db
def test_non_author_cannot_create_set(client: Client) -> None:
    org = Organization.objects.create(slug="org-a", name="A")
    client.force_login(_member("readonly", org, Role.AUDITOR))

    response = client.post(
        reverse("console:document_set_create"),
        {"organization": org.id, "logical_id": "kb", "name": "KB"},
    )
    assert response.status_code == 403
    assert not DocumentSet.objects.filter(organization=org, logical_id="kb").exists()


@pytest.mark.django_db
def test_build_job_actions_are_role_and_tenant_scoped(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("apps.ingestion.job_lifecycle.dispatch_outbox", lambda **kwargs: 0)
    org_a = Organization.objects.create(slug="job-a", name="A")
    org_b = Organization.objects.create(slug="job-b", name="B")
    version_b = _published_set_version(org_b, ["text"])
    profile_b = _granted_profile(org_b)
    job, _ = create_build_job(
        document_set_version=version_b,
        embedding_profile=profile_b,
        ocr_profile=None,
        actor="owner-b",
    )
    client.force_login(_member("owner-a", org_a, Role.PROJECT_OWNER))
    assert (
        client.post(
            reverse("console:document_set_cancel_build_job", args=[job.public_id])
        ).status_code
        == 404
    )
    client.force_login(_member("auditor-b", org_b, Role.AUDITOR))
    assert (
        client.post(
            reverse("console:document_set_cancel_build_job", args=[job.public_id])
        ).status_code
        == 403
    )
    assert AuditEvent.objects.filter(
        action="ingestion.staged_index.authorization_denied",
        outcome="failure",
        resource_id=str(job.public_id),
    ).exists()


@pytest.mark.django_db
def test_a_published_version_can_seed_the_next_one(client: Client) -> None:
    """Changing one document meant rebuilding the set from an empty draft."""

    org = Organization.objects.create(slug="branch-org", name="Branch")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    draft = create_document_set_version(document_set=document_set, actor="seed")
    for name in ("doc-1", "doc-2"):
        upload_document(
            organization=org,
            logical_id=name,
            title=name,
            mime_type="text/plain",
            data=name.encode(),
            actor="seed",
            document_set_version=draft,
        )
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))
    client.post(reverse("console:document_set_version_publish", args=[draft.id]))
    draft.refresh_from_db()

    response = client.post(reverse("console:document_set_version_branch", args=[draft.id]))

    assert response.status_code == 302
    branched = DocumentSetVersion.objects.exclude(pk=draft.pk).get(document_set=document_set)
    assert branched.status == DocumentSetVersionStatus.DRAFT
    assert branched.version == draft.version + 1
    # The source snapshot is frozen; the change becomes a new version.
    assert draft.status == DocumentSetVersionStatus.PROMOTABLE
    assert sorted(m.document_version.document.logical_id for m in branched.memberships.all()) == [
        "doc-1",
        "doc-2",
    ]
    assert AuditEvent.objects.filter(action="documents.set_version.branch").exists()


@pytest.mark.django_db
def test_branching_refuses_while_a_draft_is_already_open(client: Client) -> None:
    """Two half-finished versions would compete for the next publish."""

    org = Organization.objects.create(slug="branch-org2", name="Branch2")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    published = create_document_set_version(document_set=document_set, actor="seed")
    upload_document(
        organization=org,
        logical_id="doc-1",
        title="Doc",
        mime_type="text/plain",
        data=b"x",
        actor="seed",
        document_set_version=published,
    )
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))
    client.post(reverse("console:document_set_version_publish", args=[published.id]))
    client.post(reverse("console:document_set_version_branch", args=[published.id]))

    response = client.post(
        reverse("console:document_set_version_branch", args=[published.id]), follow=True
    )

    assert "Zaten açık bir taslak var" in response.content.decode()
    assert document_set.versions.filter(status=DocumentSetVersionStatus.DRAFT).count() == 1


@pytest.mark.django_db
def test_another_tenant_cannot_branch_a_version(client: Client) -> None:
    org = Organization.objects.create(slug="branch-home", name="Home")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    version = create_document_set_version(document_set=document_set, actor="seed")
    away = Organization.objects.create(slug="branch-away", name="Away")
    client.force_login(_member("outsider", away, Role.ORGANIZATION_ADMIN))

    response = client.post(reverse("console:document_set_version_branch", args=[version.id]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_no_jump_link_impersonates_the_action_it_scrolls_to(client: Client) -> None:
    """Step 5 offered an anchor labelled exactly like the submit button below it.

    Pressing it scrolled to a form that was already on screen, so nothing moved and the
    control read as broken — which is how a working build button was reported dead twice.
    """

    import re

    org = Organization.objects.create(slug="jump-org", name="Jump")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    version = create_document_set_version(document_set=document_set, actor="seed")
    upload_document(
        organization=org,
        logical_id="doc-1",
        title="Doc",
        mime_type="text/plain",
        data=b"x",
        actor="seed",
        document_set_version=version,
    )
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))
    client.post(reverse("console:document_set_version_publish", args=[version.id]))

    body = client.get(
        reverse("console:document_set_detail_public", args=[document_set.public_id])
    ).content.decode()

    submit_labels = {
        re.sub(r"<[^>]+>", "", match).strip()
        for match in re.findall(r'<button[^>]*type="submit"[^>]*>(.*?)</button>', body, re.S)
    }
    jump_labels = {
        re.sub(r"<[^>]+>", "", match).replace("↓", "").strip()
        for match in re.findall(r'<a[^>]*href="#[^"]*"[^>]*>(.*?)</a>', body, re.S)
    }

    assert "İndeks hazırla" in submit_labels, "the real action must still be a submit"
    assert not (submit_labels & jump_labels), (
        f"a jump link reuses an action label: {sorted(submit_labels & jump_labels)}"
    )


@pytest.mark.django_db
def test_the_build_form_holds_no_control_that_can_block_its_own_submit(client: Client) -> None:
    """The staged-index button did nothing at all, twice, and sent no request.

    The profile editors are included *inside* the build form. Their controls carry no
    ``name`` — document-profiles.js reads them and posts JSON separately — so they can never
    take part in a submission. Four of them were ``required``. An empty required control
    fails HTML5 constraint validation, and because they sit inside a collapsed <details> the
    browser cannot focus one to report it: submission is refused silently, leaving only
    "An invalid form control with name='' is not focusable" in the console.
    """

    import re

    org = Organization.objects.create(slug="submit-org", name="Submit")
    document_set = create_document_set(organization=org, logical_id="kb", name="KB", actor="seed")
    version = create_document_set_version(document_set=document_set, actor="seed")
    upload_document(
        organization=org,
        logical_id="doc-1",
        title="Doc",
        mime_type="text/plain",
        data=b"x",
        actor="seed",
        document_set_version=version,
    )
    client.force_login(_member("owner", org, Role.PROJECT_OWNER))
    client.post(reverse("console:document_set_version_publish", args=[version.id]))

    body = client.get(
        reverse("console:document_set_detail_public", args=[document_set.public_id])
    ).content.decode()

    action = reverse("console:document_set_build_index", args=[version.id])
    start = body.index(f'action="{action}"')
    form_html = body[start : body.index("</form>", start)]
    assert "İndeks hazırla" in form_html, "the build form should still carry its submit"

    controls = re.findall(r"<(?:input|select|textarea)\b[^>]*>", form_html)
    unsubmittable_required = [
        control for control in controls if "required" in control and "name=" not in control
    ]
    assert not unsubmittable_required, (
        "a control with no name can never be submitted, so it must never be required — "
        f"these would block the build form: {unsubmittable_required}"
    )
