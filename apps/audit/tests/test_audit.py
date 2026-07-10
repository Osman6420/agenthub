"""The audit trail is append-only."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.audit.services import record_event


@pytest.mark.django_db
def test_record_event_appends() -> None:
    event = record_event(
        actor_type="user",
        actor_id="alice",
        action="organization.create",
        outcome="success",
        organization_id=1,
        resource_type="organization",
        resource_id="1",
        reason="created via console",
    )
    assert event.pk is not None
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_audit_event_cannot_be_modified_or_deleted() -> None:
    event = record_event(actor_type="system", actor_id="job", action="x", outcome="success")

    event.reason = "tampered"
    with pytest.raises(ValueError):
        event.save()

    with pytest.raises(ValueError):
        event.delete()


@pytest.mark.django_db
def test_record_event_validates_enums() -> None:
    with pytest.raises(ValueError):
        record_event(actor_type="martian", actor_id="x", action="y", outcome="success")
    with pytest.raises(ValueError):
        record_event(actor_type="user", actor_id="x", action="y", outcome="maybe")
