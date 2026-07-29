from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.evaluations.models import (
    QuestionCase,
    QuestionEvaluationEvidence,
    QuestionEvaluationEvidenceStatus,
    QuestionEvaluationKind,
    QuestionEvaluationRun,
    QuestionEvaluationStatus,
    QuestionSet,
    QuestionSetVersion,
)
from apps.evaluations.question_services import create_question_set, publish_question_set
from apps.tenancy.models import Organization, OrganizationMembership, Role

pytestmark = pytest.mark.django_db


def _member(organization: Organization, username: str, role: str):
    user = get_user_model().objects.create_user(
        username=username,
        password="test-password",  # noqa: S106
    )
    OrganizationMembership.objects.create(
        organization=organization,
        user=user,
        role=role,
    )
    return user


def _cases() -> list[dict[str, object]]:
    return [
        {
            "id": "case-1",
            "question": "İade süresi nedir?",
            "input": {},
            "assertions": [{"type": "normalized_contains", "value": "14 gün"}],
            "expected_anchors": [],
        }
    ]


def test_question_set_console_creates_updates_and_publishes_exact_version() -> None:
    organization = Organization.objects.create(slug="part6", name="Part 6")
    user = _member(organization, "admin", Role.ORGANIZATION_ADMIN)
    client = Client()
    client.force_login(user)
    response = client.post(
        reverse("console:question_sets"),
        {
            "name": "Refund quality",
            "description": "Reusable benchmark",
            "cases_json": json.dumps(_cases()),
        },
    )
    question_set = QuestionSet.objects.get(organization=organization)
    assert response.status_code == 302
    assert response["Location"] == reverse(
        "console:question_set_detail", args=[question_set.public_id]
    )
    detail = client.get(response["Location"])
    assert detail.status_code == 200
    assert "Mutable taslak" in detail.content.decode()
    publish = client.post(
        reverse("console:question_set_publish", args=[question_set.public_id]),
        {"expected_revision": question_set.draft_revision},
    )
    assert publish.status_code == 302
    version = QuestionSetVersion.objects.get(question_set=question_set)
    assert version.case_count == 1
    assert version.cases.get().question == "İade süresi nedir?"


def test_auditor_cannot_read_confidential_question_set_or_mutate_it() -> None:
    organization = Organization.objects.create(slug="private", name="Private")
    admin = _member(organization, "admin", Role.ORGANIZATION_ADMIN)
    auditor = _member(organization, "auditor", Role.AUDITOR)
    question_set = create_question_set(
        organization=organization,
        user=admin,
        name="Private questions",
        description="",
        cases=_cases(),
    )
    client = Client()
    client.force_login(auditor)
    assert client.get(reverse("console:question_sets")).status_code == 404
    assert (
        client.get(
            reverse("console:question_set_detail", args=[question_set.public_id])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("console:question_set_publish", args=[question_set.public_id]),
            {"expected_revision": 1},
        ).status_code
        == 404
    )


def test_cross_tenant_question_set_identifier_is_non_disclosing() -> None:
    first = Organization.objects.create(slug="first-p6", name="First")
    second = Organization.objects.create(slug="second-p6", name="Second")
    first_admin = _member(first, "first-admin", Role.ORGANIZATION_ADMIN)
    second_admin = _member(second, "second-admin", Role.ORGANIZATION_ADMIN)
    foreign = create_question_set(
        organization=second,
        user=second_admin,
        name="Foreign",
        description="",
        cases=_cases(),
    )
    publish_question_set(
        question_set=foreign,
        user=second_admin,
        expected_revision=foreign.draft_revision,
    )
    client = Client()
    client.force_login(first_admin)
    response = client.get(reverse("console:question_set_detail", args=[foreign.public_id]))
    assert response.status_code == 404
    assert "Foreign" not in response.content.decode()


def test_evaluation_detail_filters_evidence_and_shows_safe_judge_result() -> None:
    organization = Organization.objects.create(slug="result-filter", name="Result filter")
    user = _member(organization, "result-admin", Role.ORGANIZATION_ADMIN)
    question_set = QuestionSet.objects.create(
        organization=organization,
        name="Filters",
        draft_cases=[],
        created_by=user.get_username(),
        updated_by=user.get_username(),
    )
    version = QuestionSetVersion.objects.create(
        organization=organization,
        question_set=question_set,
        version=1,
        checksum="a" * 64,
        case_count=2,
        published_by=user.get_username(),
        published_at=timezone.now(),
    )
    failed_case = QuestionCase.objects.create(
        organization=organization,
        question_set_version=version,
        ordinal=0,
        case_id="failed",
        question="Confidential failed question",
    )
    unscored_case = QuestionCase.objects.create(
        organization=organization,
        question_set_version=version,
        ordinal=1,
        case_id="unscored",
        question="Confidential unscored question",
    )
    run = QuestionEvaluationRun.objects.create(
        organization=organization,
        question_set_version=version,
        kind=QuestionEvaluationKind.ANSWER,
        status=QuestionEvaluationStatus.COMPLETED,
        idempotency_key="filter-run",
        total_cases=2,
        completed_cases=2,
        unscored_cases=1,
        created_by=user.get_username(),
    )
    QuestionEvaluationEvidence.objects.create(
        organization=organization,
        run=run,
        question_case=failed_case,
        ordinal=0,
        status=QuestionEvaluationEvidenceStatus.FAILED,
        judge={
            "status": "scored",
            "verdict": "fail",
            "reason_code": "JUDGE_FAIL",
            "model_checksum": "b" * 64,
            "prompt_checksum": "c" * 64,
        },
    )
    QuestionEvaluationEvidence.objects.create(
        organization=organization,
        run=run,
        question_case=unscored_case,
        ordinal=1,
        status=QuestionEvaluationEvidenceStatus.UNSCORED,
    )
    client = Client()
    client.force_login(user)

    response = client.get(
        reverse("console:question_evaluation_detail", args=[run.public_id]),
        {"evidence_status": "failed"},
    )

    body = response.content.decode()
    assert response.status_code == 200
    assert "Confidential failed question" not in body
    assert "Confidential unscored question" not in body
    assert "Case failed" in body
    assert "Case unscored" not in body
    assert "JUDGE_FAIL" in body
    assert "b" * 64 in body
