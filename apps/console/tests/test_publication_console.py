"""The one-action console exposes exact resumption only to current authorized owners."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.console.tests.test_scenario_step_actions import setup as setup
from apps.documents.models import DocumentSet, ScenarioDocumentSetBinding
from apps.releases import publication as service
from apps.releases.models import ScenarioPublication, ScenarioRelease
from apps.tenancy.models import OrganizationMembership

pytestmark = pytest.mark.django_db(transaction=True)


def detail(client, scenario):
    return client.get(reverse("console:scenario_detail_public", args=[scenario.public_id]))


def test_single_action_publishes_and_shows_result(client, setup):
    scenario = setup[2]
    included = DocumentSet.objects.create(
        organization=scenario.organization, logical_id="live-documents", name="Live documents"
    )
    ScenarioDocumentSetBinding.objects.create(
        organization=scenario.organization, scenario=scenario, document_set=included
    )
    page = detail(client, scenario)
    form = page.context["publication"]
    assert form["enabled"] and not form["resuming"]
    body = page.content.decode()
    advanced = body.index('id="configuration"')
    assert body.index(reverse("console:scenario_publish", args=[scenario.public_id])) < advanced
    assert (
        body.index(reverse("console:scenario_publish_and_verify", args=[scenario.public_id]))
        > advanced
    )
    response = client.post(
        reverse("console:scenario_publish", args=[scenario.public_id]),
        {"intent": str(form["intent"]), "expected": form["expected"]},
        follow=True,
    )
    assert response.status_code == 200
    assert "Testler geçti; senaryo yayına alındı." in response.content.decode()
    assert "Yayın tamamlandı" in response.content.decode()
    assert ScenarioRelease.objects.get().status == "active"
    later = DocumentSet.objects.create(
        organization=scenario.organization, logical_id="later-documents", name="Later documents"
    )
    ScenarioDocumentSetBinding.objects.create(
        organization=scenario.organization, scenario=scenario, document_set=later
    )
    page = detail(client, scenario)
    rows = {row["document_set"].pk: row for row in page.context["relationship_rows"]}
    assert rows[included.pk]["follows_active_generation"] is True
    assert rows[later.pk]["follows_active_generation"] is False
    assert "Yayında · kullanılabilir güncel veriyi takip eder" in page.content.decode()


def test_interrupted_intent_reappears_without_creating_new_candidate(client, setup):
    scenario, actor = setup[2:]
    form = detail(client, scenario).context["publication"]
    receipt = service._prepare(
        actor=actor,
        scenario=scenario,
        intent=form["intent"],
        expected=form["expected"],
        request_id="resume-ui",
    )
    updated = detail(client, scenario).context["publication"]
    assert updated["resuming"] and updated["intent"] == receipt.public_id
    assert updated["expected"] == receipt.request_checksum
    assert ScenarioRelease.objects.count() == 1


def test_auth_scope_method_csrf_and_invalid_input(client, setup):
    scenario, actor = setup[2:]
    url = reverse("console:scenario_publish", args=[scenario.public_id])
    form = detail(client, scenario).context["publication"]
    data = {"intent": str(form["intent"]), "expected": form["expected"]}
    assert Client().post(url, data).status_code == 302
    assert client.get(url).status_code == 405
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(actor)
    assert csrf_client.post(url, data).status_code == 403
    response = client.post(url, {"intent": "bad", "expected": "bad"}, follow=True)
    assert response.status_code == 200 and "Yayın isteği geçersiz" in response.content.decode()
    assert not ScenarioPublication.objects.exists()
    from django.contrib.auth import get_user_model

    viewer = get_user_model().objects.create_user("publication-outsider")
    OrganizationMembership.objects.create(organization=setup[0], user=viewer)
    client.force_login(viewer)
    assert client.post(url, data).status_code == 404
    assert detail(client, scenario).status_code == 404
    assert not ScenarioPublication.objects.exists()
