"""MCP resource UI shares exact collection authority and durable job services."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.documents.models import DocumentSet
from apps.ingestion.models import Source, StagedIndexBuildJob
from apps.ingestion.tests.test_mcp_services import create
from apps.ingestion.tests.test_mcp_services import setup as setup
from apps.ingestion.tests.test_rest_pull import governed_rest as governed_rest
from apps.tenancy.models import OrganizationMembership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def enabled(settings, monkeypatch):
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = True
    monkeypatch.setattr("apps.ingestion.job_lifecycle.dispatch_outbox", lambda **kwargs: 0)


def form_url(setup):
    return reverse("console:mcp_source_create_public", args=[setup[3].public_id])


def form_data(client, setup):
    page = client.get(form_url(setup))
    assert page.status_code == 200
    assert page.context["navigation_section"] == "documents"
    return {
        "name": "Destek belgeleri",
        "profile": str(setup[4].public_id),
        "resource_prefixes": "",
        "submission": page.context["form"]["submission"].value(),
    }


def test_create_replay_detail_and_job_controls_use_common_service(client, setup):
    client.force_login(setup[1])
    payload = form_data(client, setup)
    response = client.post(form_url(setup), payload)
    assert response.status_code == 302
    source = Source.objects.get(connector_type="mcp_resource")
    assert source.connector_config == {"resource_prefixes": ["file:///kb/"]}
    assert client.post(form_url(setup), payload).status_code == 302
    assert Source.objects.filter(connector_type="mcp_resource").count() == 1
    detail = client.get(reverse("console:connector_source_detail", args=[source.pk]))
    assert detail.status_code == 200
    assert (
        "Destek belgeleri" in detail.content.decode() and "MCP belgeleri" in detail.content.decode()
    )
    assert (
        "mcp.example.com" not in detail.content.decode()
        and "secret:" not in detail.content.decode()
    )
    assert client.post(reverse("console:connector_source_run", args=[source.pk])).status_code == 302
    job = StagedIndexBuildJob.objects.get(source=source)
    running_detail = client.get(reverse("console:connector_source_detail", args=[source.pk]))
    assert "Şimdi çalıştır" not in running_detail.content.decode()
    assert "Yenilemeyi iptal et" in running_detail.content.decode()
    action_url = reverse("console:connector_job_action", args=[source.pk, job.public_id])
    assert client.get(action_url).status_code == 405
    assert client.post(action_url, {"action": "cancel"}).status_code == 302
    job.refresh_from_db()
    assert job.status == "cancelled"
    assert client.post(action_url, {"action": "retry"}).status_code == 302
    job.refresh_from_db()
    assert job.status == "dispatch_pending"


def test_invalid_scope_preserves_form_and_cannot_create(client, setup):
    client.force_login(setup[1])
    payload = form_data(client, setup) | {"resource_prefixes": "file:///private/"}
    response = client.post(form_url(setup), payload)
    assert response.status_code == 400
    assert response.context["form"]["name"].value() == "Destek belgeleri"
    assert response.context["form"]["resource_prefixes"].value() == "file:///private/"
    assert not Source.objects.filter(connector_type="mcp_resource").exists()


def test_form_token_cannot_be_replayed_across_collection_or_tampered(client, setup):
    client.force_login(setup[0])
    payload = form_data(client, setup)
    other = DocumentSet.objects.create(organization=setup[2], logical_id="another", name="Another")
    response = client.post(
        reverse("console:mcp_source_create_public", args=[other.public_id]), payload
    )
    assert response.status_code == 400
    response = client.post(
        form_url(setup), payload | {"submission": payload["submission"] + "tamper"}
    )
    assert response.status_code == 400
    assert not Source.objects.filter(connector_type="mcp_resource").exists()


def test_same_org_membership_alone_cannot_read_source_metadata_or_act(client, setup):
    source = create(setup)
    user = get_user_model().objects.create_user("ordinary-resource-member")
    OrganizationMembership.objects.create(organization=setup[2], user=user)
    client.force_login(user)
    assert (
        client.get(reverse("console:connector_source_detail", args=[source.pk])).status_code == 404
    )
    assert client.get(form_url(setup)).status_code == 404
    assert client.post(reverse("console:connector_source_run", args=[source.pk])).status_code == 404
    # The same collection boundary now also protects preexisting REST sources.
    rest = Source.objects.get(connector_type="generic_rest")
    assert client.get(reverse("console:connector_source_detail", args=[rest.pk])).status_code == 404


def test_disabled_gate_keeps_source_visible_and_management_available(client, setup, settings):
    source = create(setup)
    client.force_login(setup[1])
    client.post(reverse("console:connector_source_run", args=[source.pk]))
    job = StagedIndexBuildJob.objects.get(source=source)
    settings.INGESTION_DURABLE_CONNECTOR_JOBS = False
    assert client.get(form_url(setup)).status_code == 404
    detail = client.get(reverse("console:connector_source_detail", args=[source.pk]))
    assert detail.status_code == 200 and "Şimdi çalıştır" not in detail.content.decode()
    assert "Yenilemeyi iptal et" in detail.content.decode()
    client.post(reverse("console:connector_source_run", args=[source.pk]))
    assert StagedIndexBuildJob.objects.filter(source=source).count() == 1
    action_url = reverse("console:connector_job_action", args=[source.pk, job.public_id])
    assert client.post(action_url, {"action": "cancel"}).status_code == 302
    job.refresh_from_db()
    assert job.status == "cancelled"


def test_mcp_source_has_no_unsupported_schedule_action(client, setup):
    source = create(setup)
    client.force_login(setup[1])
    page = client.get(reverse("console:document_set_connectors_public", args=[setup[3].public_id]))
    assert page.status_code == 200
    assert "MCP belge kaynağı ekle" in page.content.decode()
    schedule_url = reverse("console:connector_schedule_configure", args=[source.pk])
    assert schedule_url not in page.content.decode()
    assert client.post(schedule_url, {}).status_code == 403


def test_source_creation_requires_csrf(setup):
    client = Client(enforce_csrf_checks=True)
    client.force_login(setup[1])
    payload = form_data(client, setup)
    assert client.post(form_url(setup), payload).status_code == 403
    assert not Source.objects.filter(connector_type="mcp_resource").exists()


def test_missing_submission_has_a_visible_error_summary(client, setup):
    client.force_login(setup[1])
    payload = form_data(client, setup)
    del payload["submission"]
    response = client.post(form_url(setup), payload)
    assert response.status_code == 400
    assert "data-form-error-summary" in response.content.decode()
    assert "Form doğrulanamadı" in response.content.decode()
