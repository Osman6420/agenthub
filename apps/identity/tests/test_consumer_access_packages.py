from typing import Any, cast

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.console.forms import BindingForm
from apps.identity.consumer_access import (
    ConsumerAccessError,
    ConsumerAccessOptions,
    create_console_binding,
    package_capabilities,
)
from apps.identity.models import Consumer, ConsumerBinding, OrganizationResponsibilityAssignment
from apps.identity.tests.test_delegated_assignments import assignment_fixture as assignment_fixture

pytestmark = pytest.mark.django_db


def _consumer(f):
    return Consumer.objects.create(
        organization=f.organization, subject="packages", name="Packages", protocol="rest"
    )


def test_closed_packages_never_add_tools_or_inert_capabilities_implicitly():
    assert package_capabilities(ConsumerAccessOptions()) == ["workflow_run"]
    assert package_capabilities(ConsumerAccessOptions(read_tools=True, side_effect_tools=True)) == [
        "workflow_run",
        "tool_call",
        "tool_call_side_effect",
    ]
    assert package_capabilities(
        ConsumerAccessOptions(run_scenario=False, ingestion_status=True)
    ) == ["ingestion_read"]
    with pytest.raises(ConsumerAccessError, match="TOOL_ACCESS_REQUIRED"):
        package_capabilities(ConsumerAccessOptions(side_effect_tools=True))
    with pytest.raises(ConsumerAccessError, match="ACCESS_OPTION_REQUIRED"):
        package_capabilities(ConsumerAccessOptions(run_scenario=False))
    with pytest.raises(ConsumerAccessError, match="INVALID_ACCESS_OPTIONS"):
        package_capabilities(ConsumerAccessOptions(run_scenario=cast(Any, "true")))


def test_binding_service_reauthorizes_scope_and_audit_failure_rolls_back(
    assignment_fixture, monkeypatch
):
    f = assignment_fixture
    consumer = _consumer(f)
    for actor, target in ((f.editor, f.scenario), (f.administrator, f.other_scenario)):
        if target == f.other_scenario:
            # The other scenario is same-tenant and intentionally allowed to an org
            # administrator; use an actual foreign target for the negative.
            from apps.catalog.models import AIProject, Scenario

            project = AIProject.objects.create(
                organization=f.foreign_organization, slug="foreign", name="Foreign"
            )
            target = Scenario.objects.create(project=project, slug="foreign", name="Foreign")
        with pytest.raises(ConsumerAccessError):
            create_console_binding(
                consumer=consumer, scenario=target, actor=actor, options=ConsumerAccessOptions()
            )

    def unavailable(**kwargs):
        raise RuntimeError("audit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("apps.identity.consumer_access.record_event", unavailable)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            create_console_binding(
                consumer=consumer,
                scenario=f.scenario,
                actor=f.administrator,
                options=ConsumerAccessOptions(),
            )
    assert not consumer.bindings.exists()
    binding = create_console_binding(
        consumer=consumer,
        scenario=f.scenario,
        actor=f.administrator,
        options=ConsumerAccessOptions(),
    )
    assert binding.capabilities == ["workflow_run"]
    event = AuditEvent.objects.get(action="console.binding.create", outcome="success")
    assert isinstance(event.after, dict)
    assert event.after["capabilities"] == ["workflow_run"]
    OrganizationResponsibilityAssignment.objects.filter(membership__user=f.administrator).update(
        status="revoked",
        revoked_by=f.administrator,
        revoked_at=timezone.now(),
    )
    with pytest.raises(ConsumerAccessError, match="ORGANIZATION_ADMIN_REQUIRED"):
        create_console_binding(
            consumer=consumer,
            scenario=f.other_scenario,
            actor=f.administrator,
            options=ConsumerAccessOptions(),
        )


def test_form_preserves_existing_legacy_values_and_rejects_forged_capabilities(assignment_fixture):
    f = assignment_fixture
    consumer = _consumer(f)
    binding = ConsumerBinding.objects.create(
        consumer=consumer,
        scenario=f.scenario,
        capabilities=["workflow_run", "memory_read", "release_promote"],
    )
    payload = {
        "consumer": consumer.pk,
        "scenario": f.scenario.pk,
        "status": "active",
        "run_scenario": True,
        "read_tools": True,
    }
    form = BindingForm(data=payload, instance=binding, user=f.administrator)
    assert form.is_valid(), form.errors
    assert set(form.save().capabilities) == {
        "workflow_run",
        "tool_call",
        "memory_read",
        "release_promote",
    }
    forged = BindingForm(data={**payload, "capabilities": ["tool_approve"]}, user=f.administrator)
    assert not forged.is_valid()


def test_console_normal_form_saves_packages_and_gates_advanced_choices(client, assignment_fixture):
    f = assignment_fixture
    consumer = _consumer(f)
    url = reverse("console:binding_create")
    client.force_login(f.editor)
    assert client.get(url).status_code == 403
    client.force_login(f.administrator)
    page = client.get(url)
    assert page.status_code == 200
    body = page.content.decode()
    assert 'name="capabilities"' not in body and 'name="capability_preset"' not in body
    assert "Gelişmiş erişim seçenekleri" in body
    for inactive in (
        "tool_approve",
        "memory_read",
        "memory_write",
        "ingestion_trigger",
        "release_promote",
    ):
        assert inactive not in body
    payload = {
        "consumer": consumer.pk,
        "scenario": f.scenario.pk,
        "status": "active",
        "run_scenario": "on",
    }
    assert client.post(url, {**payload, "side_effect_tools": "on"}).status_code == 200
    assert not consumer.bindings.exists()
    assert client.post(url, payload).status_code == 302
    assert consumer.bindings.get().capabilities == ["workflow_run"]
