"""Retrieval diagnostics and scenario retrieval evidence.

Query-time retrieval belongs to the scenario's Retrieve node, so a document set no longer owns
a retrieval profile. These tests hold the two consequences in place: an index probe must not
require one, and a scenario answer must be able to show what it retrieved -- with the document
text itself gated on the document plane's own capability, not on scenario access.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import AuditEvent
from apps.console.retrieval_diagnostics import diagnostic_retrieval_body
from apps.documents import services as document_services
from apps.documents.models import DocumentSetVersionStatus
from apps.evaluations.question_services import (
    QuestionEvaluationError,
    ask_document_set_once,
    resolve_chunk_text,
    scenario_retrieval_evidence,
)
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
)
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.retrieval.providers import StaticRetrievalProvider
from apps.retrieval.types import RetrievedChunk
from apps.tenancy.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


def _member(organization: Organization, username: str):
    user = get_user_model().objects.create_user(
        username=username,
        password="test-password",  # noqa: S106
    )
    OrganizationMembership.objects.create(organization=organization, user=user)
    return user


def _org_admin(organization: Organization, username: str = "admin"):
    user = _member(organization, username)
    OrganizationResponsibilityAssignment.objects.create(
        organization=organization,
        membership=OrganizationMembership.objects.get(organization=organization, user=user),
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    return user


def _profileless_index(organization: Organization, user):
    """An index built the way every index is built now: with no retrieval profile."""

    document_set = document_services.create_document_set(
        organization=organization,
        logical_id="policy",
        name="Policy",
        actor="admin",
    )
    DocumentSetResponsibilityAssignment.objects.create(
        organization=organization,
        document_set=document_set,
        membership=OrganizationMembership.objects.get(organization=organization, user=user),
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=user,
    )
    set_version = document_services.create_document_set_version(
        document_set=document_set, actor="admin"
    )
    set_version.status = DocumentSetVersionStatus.ACTIVE
    set_version.save(update_fields=["status", "updated_at"])
    index = IndexVersion.objects.create(
        organization=organization,
        document_set_version=set_version,
        version=1,
        status=IndexStatus.ACTIVE,
        store_ready=True,
        dimensions=64,
        index_type="vector",
    )
    set_version.built_index_version = index
    set_version.save(update_fields=["built_index_version", "updated_at"])
    assert index.retrieval_profile_id is None
    return set_version, index


def test_the_probe_runs_against_an_index_that_has_no_retrieval_profile(monkeypatch) -> None:
    organization = Organization.objects.create(slug="probe", name="Probe")
    user = _org_admin(organization)
    set_version, index = _profileless_index(organization, user)
    monkeypatch.setattr(
        "apps.evaluations.question_services.get_retrieval_provider",
        lambda: StaticRetrievalProvider(
            [RetrievedChunk(text="Cevap", source_id="s", source_uri="policy")]
        ),
    )
    result = ask_document_set_once(
        user=user,
        document_set_version=set_version,
        index_version=index,
        profile_body=diagnostic_retrieval_body(),
        question="Politika nedir?",
    )
    assert result.chunks[0].text == "Cevap"


def test_the_diagnostic_body_is_the_authoring_form_default() -> None:
    # One definition, so a change to the form cannot leave the diagnostic behind.
    body = diagnostic_retrieval_body()
    assert body["mode"] == "hybrid"
    assert body["vector_weight"] + body["keyword_weight"] == 1.0


def test_a_probe_is_audited_when_it_runs_and_when_it_is_denied(monkeypatch) -> None:
    organization = Organization.objects.create(slug="audited", name="Audited")
    owner = _org_admin(organization)
    set_version, index = _profileless_index(organization, owner)
    monkeypatch.setattr(
        "apps.evaluations.question_services.get_retrieval_provider",
        lambda: StaticRetrievalProvider(
            [RetrievedChunk(text="Cevap", source_id="s", source_uri="policy")]
        ),
    )
    ask_document_set_once(
        user=owner,
        document_set_version=set_version,
        index_version=index,
        profile_body=diagnostic_retrieval_body(),
        question="Politika nedir?",
    )
    allowed = AuditEvent.objects.get(action="evaluation.document_set.probe", outcome="success")
    assert allowed.after == {"chunk_count": 1, "index_version_id": index.pk}

    outsider = _member(organization, "outsider")
    with pytest.raises(QuestionEvaluationError):
        ask_document_set_once(
            user=outsider,
            document_set_version=set_version,
            index_version=index,
            profile_body=diagnostic_retrieval_body(),
            question="Politika nedir?",
        )
    denied = AuditEvent.objects.get(action="evaluation.document_set.probe", outcome="deny")
    assert denied.reason == "authorization_denied"
    # A denial records that it happened, never the chunks it would have returned.
    assert denied.after in ({}, None)


def _result(sources: list[dict[str, object]], pointers: list[dict[str, object]]):
    return SimpleNamespace(output={"sources": sources}, metadata={"retrieval": pointers})


def test_evidence_pairs_sources_with_pointers_by_position() -> None:
    chunks = scenario_retrieval_evidence(
        result=_result(
            [{"source_id": "a", "source_uri": "u", "title": "T", "score": 0.9}],
            [{"index_version_id": 7, "document_version_id": 3, "ordinal": 2}],
        )
    )
    assert [(c.title, c.index_version_id, c.document_version_id, c.ordinal) for c in chunks] == [
        ("T", 7, 3, 2)
    ]
    # The pairing carries provenance, never text: text is resolved separately and authorized.
    assert chunks[0].text == ""


def test_a_length_mismatch_drops_the_pointers_instead_of_guessing() -> None:
    chunks = scenario_retrieval_evidence(
        result=_result(
            [
                {"source_id": "a", "source_uri": "u", "title": "A", "score": 0.9},
                {"source_id": "b", "source_uri": "v", "title": "B", "score": 0.8},
            ],
            [{"index_version_id": 7, "document_version_id": 3, "ordinal": 2}],
        )
    )
    assert [c.title for c in chunks] == ["A", "B"]
    assert all(c.document_version_id is None and c.index_version_id is None for c in chunks)


def test_evidence_is_empty_without_sources() -> None:
    assert scenario_retrieval_evidence(result=_result([], [{"index_version_id": 7}])) == []
    assert scenario_retrieval_evidence(result=SimpleNamespace(output={}, metadata={})) == []


def test_chunk_text_needs_document_content_authorization(monkeypatch) -> None:
    """The store is never even reached without the document-plane capability.

    Both an authorized and an unauthorized read return "" on SQLite, where the vector store does
    not exist -- so the gate is proven by whether the store is consulted at all.
    """

    organization = Organization.objects.create(slug="content", name="Content")
    owner = _org_admin(organization)
    _, index = _profileless_index(organization, owner)
    stranger = _member(organization, "stranger")
    reads: list[tuple[int, int]] = []

    def _record(index_version: object, document_version_id: int, ordinal: int) -> str:
        reads.append((document_version_id, ordinal))
        return "Gizli metin"

    monkeypatch.setattr("apps.evaluations.question_services.exact_chunk_text", _record)

    assert (
        resolve_chunk_text(
            user=stranger,
            organization_id=organization.pk,
            index_version_id=index.pk,
            document_version_id=1,
            ordinal=0,
        )
        == ""
    )
    assert reads == []

    assert (
        resolve_chunk_text(
            user=owner,
            organization_id=organization.pk,
            index_version_id=index.pk,
            document_version_id=1,
            ordinal=0,
        )
        == "Gizli metin"
    )
    assert reads == [(1, 0)]


def test_chunk_text_refuses_an_index_from_another_tenant(monkeypatch) -> None:
    organization = Organization.objects.create(slug="own", name="Own")
    other = Organization.objects.create(slug="other", name="Other")
    owner = _org_admin(organization)
    _, index = _profileless_index(organization, owner)
    monkeypatch.setattr(
        "apps.evaluations.question_services.exact_chunk_text",
        lambda *_args: pytest.fail("a pointer from another tenant reached the vector store"),
    )
    assert (
        resolve_chunk_text(
            user=owner,
            organization_id=other.pk,
            index_version_id=index.pk,
            document_version_id=1,
            ordinal=0,
        )
        == ""
    )


def test_chunk_text_ignores_a_malformed_pointer() -> None:
    organization = Organization.objects.create(slug="malformed", name="Malformed")
    owner = _org_admin(organization)
    _, index = _profileless_index(organization, owner)
    assert (
        resolve_chunk_text(
            user=owner,
            organization_id=organization.pk,
            index_version_id=index.pk,
            document_version_id="3",
            ordinal=None,
        )
        == ""
    )
