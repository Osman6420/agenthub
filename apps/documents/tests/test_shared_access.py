"""Shared data is explicit, per-set, live, and never granted by a scenario manager alone."""

import pytest

from apps.audit.models import AuditEvent
from apps.documents.access_services import (
    ScenarioDocumentSetAccessError,
    grant_scenario_document_set_access_if_authorized,
    revoke_scenario_document_set_grant,
)
from apps.documents.models import ScenarioDocumentSetGrant
from apps.documents.retrieve_scope import live_consumer_scenario_grants
from apps.documents.shared_access import set_scenario_data_access_mode, set_shared_consumer_consent
from apps.documents.tests.test_scenario_access import access_fixture as access_fixture
from apps.identity.models import Consumer, ConsumerBinding

pytestmark = pytest.mark.django_db


def _granted(f):
    return grant_scenario_document_set_access_if_authorized(
        scenario=f["scenario"], document_set=f["document_set"], actor=f["manager"]
    )


def _consumer(f, name="client"):
    consumer = Consumer.objects.create(
        organization=f["organization"], name=name, subject=name, protocol="rest"
    )
    ConsumerBinding.objects.create(
        consumer=consumer, scenario=f["scenario"], capabilities=["workflow_run"]
    )
    return consumer


def _sets(f, consumer):
    return list(
        live_consumer_scenario_grants(
            consumer=consumer, scenario_ids=[f["scenario"].pk]
        ).values_list("document_set_id", flat=True)
    )


def test_shared_consent_requires_data_owner_ack_and_mode_then_includes_future_callers(
    access_fixture,
):
    f = access_fixture
    grant = _granted(f)
    consumer = _consumer(f)
    assert not _sets(f, consumer)
    for actor, ack, reason in (
        (f["project_admin"], True, "DOCUMENT_SET_MANAGER_REQUIRED"),
        (f["admin"], True, "DOCUMENT_SET_MANAGER_REQUIRED"),
        (f["manager"], False, "SHARED_FUTURE_CONSUMERS_ACK_REQUIRED"),
    ):
        with pytest.raises(ScenarioDocumentSetAccessError, match=reason):
            set_shared_consumer_consent(
                grant=grant, actor=actor, enabled=True, acknowledge_future_consumers=ack
            )
    set_shared_consumer_consent(
        grant=grant, actor=f["manager"], enabled=True, acknowledge_future_consumers=True
    )
    assert not _sets(f, consumer)  # legacy consumer-specific mode is unchanged
    set_scenario_data_access_mode(
        scenario=f["scenario"], actor=f["project_admin"], mode="scenario_shared"
    )
    assert _sets(f, consumer) == [f["document_set"].pk]
    future = _consumer(f, "future")
    assert _sets(f, future) == [f["document_set"].pk]
    future.bindings.update(status="revoked")
    assert not _sets(f, future)
    event = AuditEvent.objects.get(
        action="scenario_document_set_access.shared_consent", outcome="success"
    )
    assert isinstance(event.after, dict)
    assert event.after["includes_future_authorized_consumers"] is True


def test_revocation_is_live_and_normal_regrant_cannot_restore_shared_consent(access_fixture):
    f = access_fixture
    grant = _granted(f)
    consumer = _consumer(f)
    set_scenario_data_access_mode(
        scenario=f["scenario"], actor=f["project_admin"], mode="scenario_shared"
    )
    assert not _sets(f, consumer)
    set_shared_consumer_consent(
        grant=grant, actor=f["manager"], enabled=True, acknowledge_future_consumers=True
    )
    assert _sets(f, consumer)
    revoke_scenario_document_set_grant(grant=grant, actor=f["manager"])
    assert not _sets(f, consumer)
    grant.refresh_from_db()
    assert not grant.shared_consumers and grant.shared_approved_by is None
    _granted(f)
    assert not _sets(f, consumer)
    set_shared_consumer_consent(
        grant=grant, actor=f["manager"], enabled=True, acknowledge_future_consumers=True
    )
    set_shared_consumer_consent(grant=grant, actor=f["manager"], enabled=False)
    assert not _sets(f, consumer)


def test_shared_change_is_atomic_with_audit_and_cannot_cross_scope_or_use_unknown_mode(
    access_fixture, monkeypatch
):
    f = access_fixture
    grant = _granted(f)

    def fail(**kwargs):
        raise RuntimeError("audit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("apps.documents.shared_access.record_event", fail)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            set_shared_consumer_consent(
                grant=grant, actor=f["manager"], enabled=True, acknowledge_future_consumers=True
            )
    grant.refresh_from_db()
    assert not grant.shared_consumers
    with pytest.raises(ScenarioDocumentSetAccessError, match="INVALID_DATA_ACCESS_MODE"):
        set_scenario_data_access_mode(
            scenario=f["scenario"], actor=f["project_admin"], mode="unknown"
        )
    with pytest.raises(ScenarioDocumentSetAccessError, match="SCENARIO_EDIT_REQUIRED"):
        set_scenario_data_access_mode(
            scenario=f["scenario"], actor=f["manager"], mode="scenario_shared"
        )
    assert not ScenarioDocumentSetGrant.objects.filter(shared_consumers=True).exists()
