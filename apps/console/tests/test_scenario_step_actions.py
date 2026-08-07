"""Each setup step reaches its own destination, and acts without leaving the page."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import AIProject, LifecycleStatus, Scenario
from apps.evaluations.models import QuestionSet
from apps.identity.models import (
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


def _admin(org: Organization, project: AIProject, username: str) -> Any:
    user = User.objects.create_user(username, password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=user)
    OrganizationResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        responsibility=OrganizationResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    ProjectResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        project=project,
        responsibility=ProjectResponsibility.ADMINISTRATOR,
        assigned_by=user,
    )
    return user


def _new_scenario(client: Client, org: Organization, project: AIProject) -> Scenario:
    client.post(
        reverse("console:project_scenario_create", args=[project.public_id]),
        {"name": "Adım senaryosu", "preset": "empty_workflow", "logical_description": "Amaç"},
    )
    return Scenario.objects.get(project=project)


@pytest.fixture
def setup(client: Client) -> tuple[Organization, AIProject, Scenario, Any]:
    org = Organization.objects.create(slug="step-org", name="Step")
    project = AIProject.objects.create(organization=org, slug="p", name="P")
    admin = _admin(org, project, "step-admin")
    client.force_login(admin)
    scenario = _new_scenario(client, org, project)
    # Creating a scenario grants neither responsibility: authoring and promotion are exact,
    # scenario-scoped roles. The fixture holds both so a single test can isolate one of them.
    membership = OrganizationMembership.objects.get(organization=org, user=admin)
    for responsibility in (
        ScenarioResponsibility.EDITOR,
        ScenarioResponsibility.RELEASE_MANAGER,
    ):
        ScenarioResponsibilityAssignment.objects.create(
            organization=org,
            membership=membership,
            scenario=scenario,
            responsibility=responsibility,
            assigned_by=admin,
        )
    return org, project, scenario, admin


def test_the_three_authoring_steps_no_longer_share_one_destination(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    _org, _project, scenario, _admin_user = setup
    detail = reverse("console:scenario_detail_public", args=[scenario.public_id])

    body = client.get(detail).content.decode()

    # Step 4 has its own page; step 5 acts in place instead of linking to Studio.
    assert reverse("console:scenario_test_questions", args=[scenario.public_id]) in body
    assert reverse("console:scenario_publish_and_verify", args=[scenario.public_id]) in body
    # Step 6 stays disabled until there is something to promote, so it offers no action yet.
    assert reverse("console:scenario_promote", args=[scenario.public_id]) not in body

    client.post(reverse("console:scenario_publish_and_verify", args=[scenario.public_id]))

    assert (
        reverse("console:scenario_promote", args=[scenario.public_id])
        in client.get(detail).content.decode()
    )


def test_publish_and_verify_runs_from_the_scenario_page(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    _org, _project, scenario, _admin_user = setup

    response = client.post(
        reverse("console:scenario_publish_and_verify", args=[scenario.public_id])
    )

    assert response.status_code == 302
    release = ScenarioRelease.objects.get(scenario=scenario)
    assert release.status == ReleaseStatus.CANDIDATE
    # The result page links straight to the candidate instead of making it be hunted for.
    body = client.get(
        reverse("console:scenario_detail_public", args=[scenario.public_id])
    ).content.decode()
    assert reverse("console:release_detail", args=[release.pk]) in body


def test_promoting_also_makes_the_scenario_callable(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    """Activation used to be a second, mandatory action hidden under "Gelişmiş"."""

    _org, _project, scenario, _admin_user = setup
    client.post(reverse("console:scenario_publish_and_verify", args=[scenario.public_id]))

    response = client.post(reverse("console:scenario_promote", args=[scenario.public_id]))

    assert response.status_code == 302
    release = ScenarioRelease.objects.get(scenario=scenario)
    assert release.status == ReleaseStatus.ACTIVE
    scenario.refresh_from_db()
    assert scenario.status == LifecycleStatus.ACTIVE


def test_promotion_without_a_candidate_says_so(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    _org, _project, scenario, _admin_user = setup

    response = client.post(
        reverse("console:scenario_promote", args=[scenario.public_id]), follow=True
    )

    assert "Yayına alınabilecek yeni bir aday sürüm yok." in response.content.decode()
    assert not ScenarioRelease.objects.filter(status=ReleaseStatus.ACTIVE).exists()


def test_test_questions_save_rows_and_republish_the_suite(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    _org, _project, scenario, _admin_user = setup
    url = reverse("console:scenario_test_questions", args=[scenario.public_id])

    response = client.post(
        url,
        {
            "question": ["Kargo ne zaman gelir?", "İade süresi?"],
            "mode": ["contains", "judge"],
            "expected": ["3 iş günü", "Adımları anlatmalı"],
            "require_citation": ["0"],
        },
        follow=True,
    )

    assert response.status_code == 200
    question_set = QuestionSet.objects.get(scenario=scenario)
    assert [case["question"] for case in question_set.draft_cases] == [
        "Kargo ne zaman gelir?",
        "İade süresi?",
    ]
    # Round-trips into the editor rather than forcing the author to retype.
    body = client.get(url).content.decode()
    assert "Kargo ne zaman gelir?" in body
    assert "Adımları anlatmalı" in body


def test_a_scenario_editor_may_author_but_not_promote(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    org, _project, scenario, admin = setup
    editor = User.objects.create_user("step-editor", password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=org, user=editor)
    ScenarioResponsibilityAssignment.objects.create(
        organization=org,
        membership=membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=admin,
    )
    client.force_login(editor)

    assert (
        client.post(
            reverse("console:scenario_test_questions", args=[scenario.public_id]),
            {"question": ["Soru"], "mode": ["contains"], "expected": ["cevap"]},
        ).status_code
        == 200
    )
    assert (
        client.post(
            reverse("console:scenario_publish_and_verify", args=[scenario.public_id])
        ).status_code
        == 302
    )
    assert (
        client.post(reverse("console:scenario_promote", args=[scenario.public_id])).status_code
        == 403
    )


def test_a_waiting_candidate_keeps_step_six_open(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    """Step 6 used to report "done" for any active release, hiding an unpromoted fix."""

    _org, _project, scenario, _admin_user = setup
    publish = reverse("console:scenario_publish_and_verify", args=[scenario.public_id])
    detail = reverse("console:scenario_detail_public", args=[scenario.public_id])
    client.post(publish)
    client.post(reverse("console:scenario_promote", args=[scenario.public_id]))
    active = ScenarioRelease.objects.get(scenario=scenario, status=ReleaseStatus.ACTIVE)

    # Nothing is waiting: the step is genuinely finished and offers no action.
    settled = client.get(detail).content.decode()
    assert f"Aktif release #{active.pk}." in settled
    assert reverse("console:scenario_promote", args=[scenario.public_id]) not in settled

    # A new candidate reopens it, and says the live behaviour has not changed yet.
    client.post(publish)
    candidate = ScenarioRelease.objects.filter(
        scenario=scenario, status=ReleaseStatus.CANDIDATE
    ).latest("pk")
    body = client.get(detail).content.decode()

    assert f"Aday #{candidate.pk} hazır ama yayında #{active.pk} var." in body
    assert reverse("console:scenario_promote", args=[scenario.public_id]) in body


def test_promotion_never_reaches_back_to_a_superseded_candidate(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    """Promoting "the newest candidate" would put stale work live after a promotion."""

    _org, _project, scenario, _admin_user = setup
    publish = reverse("console:scenario_publish_and_verify", args=[scenario.public_id])
    promote = reverse("console:scenario_promote", args=[scenario.public_id])
    client.post(publish)
    stale = ScenarioRelease.objects.get(scenario=scenario)
    client.post(publish)
    client.post(promote)

    response = client.post(promote, follow=True)

    stale.refresh_from_db()
    assert stale.status == ReleaseStatus.CANDIDATE
    assert "Yayına alınabilecek yeni bir aday sürüm yok." in response.content.decode()


def test_another_tenant_cannot_reach_the_step_actions(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    _org, _project, scenario, _admin_user = setup
    other = Organization.objects.create(slug="step-other", name="Other")
    other_project = AIProject.objects.create(organization=other, slug="op", name="OP")
    client.force_login(_admin(other, other_project, "step-outsider"))

    for route in (
        "console:scenario_test_questions",
        "console:scenario_publish_and_verify",
        "console:scenario_promote",
    ):
        assert client.post(reverse(route, args=[scenario.public_id])).status_code == 404


def test_every_generated_curl_example_carries_valid_json(
    client: Client, setup: tuple[Organization, AIProject, Scenario, Any]
) -> None:
    """The chat example used to be built with a literal ``}}`` in a non-f-string line.

    Anyone who copied it got ``VALIDATION_ERROR`` from the gateway for a payload the console
    itself had malformed.
    """

    import json
    import re

    _org, _project, scenario, _admin_user = setup
    client.post(reverse("console:scenario_publish_and_verify", args=[scenario.public_id]))
    client.post(reverse("console:scenario_promote", args=[scenario.public_id]))

    body = client.get(
        reverse("console:scenario_detail_public", args=[scenario.public_id])
    ).content.decode()

    payloads = re.findall(r"-d &#x27;(\{.*?\})&#x27;", body) or re.findall(r"-d '(\{.*?\})'", body)
    assert payloads, "the scenario page should offer at least one runnable curl example"
    for payload in payloads:
        json.loads(payload.replace("&quot;", '"'))
