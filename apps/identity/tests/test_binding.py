"""Consumer binding validation and fail-closed resolution."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import (
    AIProject,
    AliasStatus,
    LifecycleStatus,
    Scenario,
    ScenarioAlias,
    ScenarioType,
)
from apps.identity.models import (
    BindingStatus,
    Consumer,
    ConsumerBinding,
    ConsumerProtocol,
    ConsumerStatus,
    ConsumerToken,
)
from apps.identity.services import resolve_active_binding
from apps.tenancy.models import Organization


def _scenario(org: Organization, *, active: bool = True) -> Scenario:
    project = AIProject.objects.create(organization=org, slug="p", name="P")
    return Scenario.objects.create(
        project=project,
        slug="s",
        name="S",
        type=ScenarioType.RAG,
        status=LifecycleStatus.ACTIVE if active else LifecycleStatus.DRAFT,
    )


def _consumer(org: Organization, *, active: bool = True) -> Consumer:
    return Consumer.objects.create(
        organization=org,
        subject="svc-1",
        name="Backend",
        protocol=ConsumerProtocol.REST,
        status=ConsumerStatus.ACTIVE if active else ConsumerStatus.DISABLED,
    )


@pytest.mark.django_db
def test_binding_rejects_unknown_capability() -> None:
    org = Organization.objects.create(slug="o", name="O")
    scenario = _scenario(org)
    consumer = _consumer(org)
    with pytest.raises(ValidationError):
        ConsumerBinding(
            consumer=consumer, scenario=scenario, capabilities=["query", "bogus"]
        ).save()


@pytest.mark.django_db
def test_binding_rejects_cross_organization() -> None:
    org_a = Organization.objects.create(slug="a", name="A")
    org_b = Organization.objects.create(slug="b", name="B")
    scenario_b = _scenario(org_b)
    consumer_a = _consumer(org_a)
    with pytest.raises(ValidationError):
        ConsumerBinding(consumer=consumer_a, scenario=scenario_b, capabilities=["query"]).save()


@pytest.mark.django_db
def test_direct_identity_lineage_rejects_explicit_mismatch() -> None:
    org_a = Organization.objects.create(slug="lineage-a", name="A")
    org_b = Organization.objects.create(slug="lineage-b", name="B")
    scenario_a = _scenario(org_a)
    consumer_a = _consumer(org_a)

    with pytest.raises(ValidationError, match="binding organization must match"):
        ConsumerBinding(
            organization=org_b,
            consumer=consumer_a,
            scenario=scenario_a,
            capabilities=["query"],
        ).save()
    with pytest.raises(ValueError, match="token organization must match"):
        ConsumerToken(
            organization=org_b,
            consumer=consumer_a,
            name="bad",
            prefix="bad",
            token_hash="f" * 64,
        ).save()


@pytest.mark.django_db
def test_resolve_happy_path_and_denials() -> None:
    org = Organization.objects.create(slug="o", name="O")
    scenario = _scenario(org)
    ScenarioAlias.objects.create(
        scenario=scenario, alias="customer-information", status=AliasStatus.ACTIVE
    )
    consumer = _consumer(org)
    ConsumerBinding.objects.create(
        consumer=consumer,
        scenario=scenario,
        capabilities=["query"],
        status=BindingStatus.ACTIVE,
    )

    resolved = resolve_active_binding(
        organization_id=org.id, subject="svc-1", alias="customer-information"
    )
    assert resolved is not None
    assert resolved.capabilities == frozenset({"query"})

    # Unknown alias -> deny.
    assert resolve_active_binding(organization_id=org.id, subject="svc-1", alias="nope") is None


@pytest.mark.django_db
def test_resolve_denies_disabled_consumer() -> None:
    org = Organization.objects.create(slug="o", name="O")
    scenario = _scenario(org)
    ScenarioAlias.objects.create(scenario=scenario, alias="a")
    consumer = _consumer(org, active=False)  # disabled
    ConsumerBinding.objects.create(consumer=consumer, scenario=scenario, capabilities=["query"])

    assert resolve_active_binding(organization_id=org.id, subject="svc-1", alias="a") is None


@pytest.mark.django_db
def test_resolve_denies_disabled_binding() -> None:
    org = Organization.objects.create(slug="o", name="O")
    scenario = _scenario(org)
    ScenarioAlias.objects.create(scenario=scenario, alias="a")
    consumer = _consumer(org)
    ConsumerBinding.objects.create(
        consumer=consumer,
        scenario=scenario,
        capabilities=["query"],
        status=BindingStatus.DISABLED,
    )

    assert resolve_active_binding(organization_id=org.id, subject="svc-1", alias="a") is None
