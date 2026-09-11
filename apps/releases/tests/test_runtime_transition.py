"""Reviewed configuration opt-in never changes an already-serving release."""

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.builder.models import WorkflowDraft
from apps.console.tests.test_scenario_step_actions import setup as setup
from apps.identity.models import ScenarioResponsibilityAssignment
from apps.releases import runtime_transition as service
from apps.releases.models import ScenarioRelease
from apps.releases.publication import PublicationError, publication_token, publish_scenario

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def legacy(setup):
    scenario, actor = setup[2:]
    scenario.execution_contract = "legacy"
    scenario.data_selection = "legacy_pinned"
    scenario.save(update_fields=["execution_contract", "data_selection"])
    return scenario, actor


def test_review_enable_replay_and_subsequent_publication_keep_old_live_until_pass(legacy, client):
    scenario, actor = legacy
    previous = publish_scenario(
        actor=actor, scenario=scenario, intent=uuid4(), expected=publication_token(scenario)
    ).release
    scenario.refresh_from_db()
    client.force_login(actor)
    url = reverse("console:scenario_runtime_transition", args=[scenario.public_id])
    page = client.get(url)
    assert page.status_code == 200
    review = page.context["transition"]["review"]
    assert client.post(url, {"review": review, "execution_contract": "legacy"}).status_code == 400
    assert client.post(url, {"review": review}).status_code == 302
    assert client.post(url, {"review": review}).status_code == 302
    previous.refresh_from_db()
    scenario.refresh_from_db()
    assert scenario.data_selection == "active_generation"
    assert previous.status == "active" and previous.execution_contract == "legacy"
    assert ScenarioRelease.objects.count() == 1
    assert AuditEvent.objects.filter(action="scenario.runtime.transitioned").count() == 1
    receipt = publish_scenario(
        actor=actor, scenario=scenario, intent=uuid4(), expected=publication_token(scenario)
    )
    assert receipt.completed_at and receipt.release.execution_contract == "scenario-revision/v1"
    previous.refresh_from_db()
    assert previous.status == "superseded"


def test_stale_review_and_revoked_actor_cannot_change_configuration(legacy):
    scenario, actor = legacy
    review = service.preview_runtime_transition(actor=actor, scenario=scenario)["review"]
    draft = WorkflowDraft.objects.get(scenario=scenario)
    draft.revision += 1
    draft.save(update_fields=["revision"])
    with pytest.raises(PublicationError, match="SETTINGS_CHANGED"):
        service.enable_runtime_snapshot(actor=actor, scenario=scenario, review=review)
    ScenarioResponsibilityAssignment.objects.filter(membership__user=actor).update(
        status="revoked",
        revoked_at=timezone.now(),
        revoked_by=actor,
    )
    with pytest.raises(PermissionDenied):
        service.enable_runtime_snapshot(actor=actor, scenario=scenario, review=review)
    scenario.refresh_from_db()
    assert scenario.execution_contract == "legacy"


def test_audit_failure_rolls_back_configuration_and_forged_review_is_denied(legacy, monkeypatch):
    scenario, actor = legacy
    with pytest.raises(PublicationError, match="REVIEW_EXPIRED"):
        service.enable_runtime_snapshot(actor=actor, scenario=scenario, review="forged")
    review = service.preview_runtime_transition(actor=actor, scenario=scenario)["review"]
    original = service.record_event

    def fail(**kwargs):
        if kwargs["action"] == "scenario.runtime.transitioned":
            raise RuntimeError("audit unavailable")
        return original(**kwargs)

    monkeypatch.setattr(service, "record_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.enable_runtime_snapshot(actor=actor, scenario=scenario, review=review)
    scenario.refresh_from_db()
    assert scenario.execution_contract == "legacy" and scenario.data_selection == "legacy_pinned"
