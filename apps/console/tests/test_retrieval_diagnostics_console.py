"""The console surfaces that had to run a query after retrieval moved to the Retrieve node.

An index built today carries no retrieval profile. The probe used to refuse such an index
outright, and the batch evaluation quietly dropped it from its target list -- so the operator
saw either one opaque error or an empty control with no reason.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.console.retrieval_diagnostics import (
    DIAGNOSTIC_LOGICAL_ID,
    diagnostic_retrieval_body,
)
from apps.console.tests.access_fixtures import private_access_member
from apps.documents import services as document_services
from apps.documents.models import DocumentSetVersionStatus
from apps.evaluations.models import QuestionEvaluationRun
from apps.evaluations.question_services import create_question_set, publish_question_set
from apps.identity.models import (
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.retrieval.providers import StaticRetrievalProvider
from apps.retrieval.types import RetrievedChunk
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


def _admin(org: Organization, username: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    OrganizationResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    return user


def _document_set_with_index(org: Organization, user: Any, *, ready: bool = True):
    document_set = document_services.create_document_set(
        organization=org, logical_id="policy", name="Policy", actor="admin"
    )
    DocumentSetResponsibilityAssignment.objects.create(
        organization=org,
        document_set=document_set,
        membership=OrganizationMembership.objects.get(organization=org, user=user),
        responsibility=DocumentSetResponsibility.MANAGER,
        assigned_by=user,
    )
    set_version = document_services.create_document_set_version(
        document_set=document_set, actor="admin"
    )
    set_version.status = DocumentSetVersionStatus.ACTIVE
    set_version.save(update_fields=["status", "updated_at"])
    if not ready:
        return document_set, set_version, None
    index = IndexVersion.objects.create(
        organization=org,
        document_set_version=set_version,
        version=1,
        status=IndexStatus.ACTIVE,
        store_ready=True,
        dimensions=64,
        index_type="vector",
    )
    set_version.built_index_version = index
    set_version.save(update_fields=["built_index_version", "updated_at"])
    return document_set, set_version, index


@pytest.fixture
def setup(client: Client) -> tuple[Organization, Any]:
    org = Organization.objects.create(slug="diag-org", name="Diag")
    admin = _admin(org, "diag-admin")
    client.force_login(admin)
    return org, admin


def test_the_probe_runs_against_a_profile_less_index(
    client: Client, setup: tuple[Organization, Any], monkeypatch
) -> None:
    org, admin = setup
    document_set, _version, _index = _document_set_with_index(org, admin)
    monkeypatch.setattr(
        "apps.evaluations.question_services.get_retrieval_provider",
        lambda: StaticRetrievalProvider(
            [RetrievedChunk(text="Politika metni", source_id="s", source_uri="policy")]
        ),
    )

    response = client.post(
        reverse("console:document_set_ask", args=[document_set.public_id]),
        {"question": "Politika nedir?"},
    )

    assert response.status_code == 200
    assert "Politika metni" in response.content.decode()


def test_a_refused_probe_names_the_precondition_that_failed(
    client: Client, setup: tuple[Organization, Any]
) -> None:
    org, admin = setup
    document_set, _version, _index = _document_set_with_index(org, admin, ready=False)

    body = client.post(
        reverse("console:document_set_ask", args=[document_set.public_id]),
        {"question": "Politika nedir?"},
        follow=True,
    ).content.decode()

    # Not one message for every cause: this one says the index is missing, not the version.
    assert "hazır bir indeksi yok" in body


def _published_question_set(org: Organization, user: Any):
    question_set = create_question_set(
        organization=org,
        user=user,
        name="Kıyas",
        description="Sorular",
        cases=[
            {
                "id": "q1",
                "question": "İade süresi nedir?",
                "expected_anchors": [{"document_version_id": 1, "ordinal": 0}],
            }
        ],
    )
    publish_question_set(
        question_set=question_set, user=user, expected_revision=question_set.draft_revision
    )
    return question_set


def test_a_profile_less_index_is_offered_as_a_batch_target(
    client: Client, setup: tuple[Organization, Any]
) -> None:
    org, admin = setup
    _set, set_version, index = _document_set_with_index(org, admin)
    question_set = _published_question_set(org, admin)

    body = client.get(
        reverse("console:question_set_detail", args=[question_set.public_id])
    ).content.decode()

    # The target value no longer carries the profile primary key through the client.
    assert f'value="{set_version.pk}:{index.pk}"' in body


def test_an_empty_target_list_says_why(client: Client, setup: tuple[Organization, Any]) -> None:
    org, admin = setup
    question_set = _published_question_set(org, admin)

    body = client.get(
        reverse("console:question_set_detail", args=[question_set.public_id])
    ).content.decode()

    assert "Henüz hazır bir indeks yok" in body


def test_a_batch_run_pins_the_diagnostic_profile_and_reuses_it(
    client: Client, setup: tuple[Organization, Any]
) -> None:
    org, admin = setup
    _set, set_version, index = _document_set_with_index(org, admin)
    question_set = _published_question_set(org, admin)
    version = question_set.versions.get()
    url = reverse("console:question_set_start_retrieval", args=[question_set.public_id])

    for key in ("run-one", "run-two"):
        client.post(
            url,
            {
                "question_set_version": str(version.public_id),
                "target": f"{set_version.pk}:{index.pk}",
                "idempotency_key": key,
            },
        )

    runs = list(QuestionEvaluationRun.objects.filter(organization=org))
    assert len(runs) == 2
    pinned = {run.retrieval_profile for run in runs}
    # A persisted report points at a checksummed body; a second run reuses the same version
    # rather than publishing a new one that means exactly the same thing.
    assert len(pinned) == 1
    profile = pinned.pop()
    assert profile is not None
    assert profile.logical_id == DIAGNOSTIC_LOGICAL_ID
    assert profile.body == diagnostic_retrieval_body()
    assert (
        ArtifactVersion.objects.filter(
            organization=org,
            type=ArtifactType.RETRIEVAL_PROFILE,
            logical_id=DIAGNOSTIC_LOGICAL_ID,
        ).count()
        == 1
    )


def _served_scenario(client: Client, org: Organization, admin: Any) -> Scenario:
    """A scenario with an active release, which is what makes the ask section render."""

    project = AIProject.objects.create(organization=org, slug="p", name="P")
    ProjectResponsibilityAssignment.objects.create(
        organization=org,
        membership=OrganizationMembership.objects.get(organization=org, user=admin),
        project=project,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=admin,
    )
    client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {
            "access_mode": "private",
            "initial_manager": private_access_member(org),
            "name": "Kanıt senaryosu",
            "preset": "empty_workflow",
            "logical_description": "Amaç",
        },
    )
    scenario = Scenario.objects.get(project=project)
    for responsibility in (
        ScenarioResponsibility.EDITOR,
        ScenarioResponsibility.RELEASE_MANAGER,
    ):
        ScenarioResponsibilityAssignment.objects.create(
            organization=org,
            membership=OrganizationMembership.objects.get(organization=org, user=admin),
            scenario=scenario,
            responsibility=responsibility,
            assigned_by=admin,
        )
    client.post(reverse("console:scenario_publish_and_verify", args=[scenario.public_id]))
    client.post(reverse("console:scenario_promote", args=[scenario.public_id]))
    return scenario


def test_the_scenario_answer_shows_what_it_retrieved(
    client: Client, setup: tuple[Organization, Any], monkeypatch
) -> None:
    """Without the evidence an author cannot tell a retrieval problem from a prompt problem."""

    org, admin = setup
    _set, _version, index = _document_set_with_index(org, admin)
    scenario = _served_scenario(client, org, admin)
    monkeypatch.setattr(
        "apps.evaluations.question_services.exact_chunk_text",
        lambda *_args: "Kargo 3 iş günü içinde teslim edilir.",
    )
    session = client.session
    session["scenario_ask"] = {
        "scenario": str(scenario.public_id),
        "question": "Kargo ne zaman gelir?",
        "answer": "3 iş günü.",
        "chunks": [
            {
                "title": "Teslimat",
                "score": 0.91,
                "source_uri": "policy://teslimat",
                "index_version_id": index.pk,
                "document_version_id": 4,
                "ordinal": 1,
            }
        ],
    }
    session.save()

    body = client.get(
        reverse("console:scenario_detail_public", args=[scenario.public_id])
    ).content.decode()

    assert "Bu cevap neye dayandı?" in body
    assert "Teslimat" in body
    assert "policy://teslimat" in body
    assert "Kargo 3 iş günü içinde teslim edilir." in body


def test_the_answer_shows_provenance_but_not_text_without_content_access(
    client: Client, setup: tuple[Organization, Any], monkeypatch
) -> None:
    org, admin = setup
    _set, _version, index = _document_set_with_index(org, admin)
    scenario = _served_scenario(client, org, admin)
    monkeypatch.setattr(
        "apps.evaluations.question_services.exact_chunk_text",
        lambda *_args: "Gizli metin",
    )
    # A scenario tester with no document-set responsibility: they may see where an answer came
    # from, never what the source said.
    tester = User.objects.create_user("diag-tester", password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=tester)
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=admin,
    )
    client.force_login(tester)
    session = client.session
    session["scenario_ask"] = {
        "scenario": str(scenario.public_id),
        "question": "Kargo ne zaman gelir?",
        "answer": "3 iş günü.",
        "chunks": [
            {
                "title": "Teslimat",
                "score": 0.91,
                "source_uri": "policy://teslimat",
                "index_version_id": index.pk,
                "document_version_id": 4,
                "ordinal": 1,
            }
        ],
    }
    session.save()

    body = client.get(
        reverse("console:scenario_detail_public", args=[scenario.public_id])
    ).content.decode()

    assert "Teslimat" in body
    assert "Gizli metin" not in body
    assert "doküman içeriği okuma yetkisi gerekir" in body


def test_another_tenants_index_is_not_a_target(
    client: Client, setup: tuple[Organization, Any]
) -> None:
    org, admin = setup
    other = Organization.objects.create(slug="diag-other", name="Other")
    other_admin = _admin(other, "diag-other-admin")
    _set, foreign_version, foreign_index = _document_set_with_index(other, other_admin)
    question_set = _published_question_set(org, admin)

    body = client.get(
        reverse("console:question_set_detail", args=[question_set.public_id])
    ).content.decode()

    assert f'value="{foreign_version.pk}:{foreign_index.pk}"' not in body
