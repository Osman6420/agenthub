"""Scenario callability lifecycle is explicit, exact-scope, atomic, and audited."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import AuditEvent
from apps.catalog.lifecycle import (
    ScenarioLifecycleError,
    activate_scenario,
    disable_scenario,
)
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias
from apps.documents.models import DocumentSet, DocumentSetVersion, DocumentSetVersionStatus
from apps.identity.models import (
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
)
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization, OrganizationMembership

User = get_user_model()


def _fixture(*, responsibility: str = ScenarioResponsibility.RELEASE_MANAGER):
    organization = Organization.objects.create(slug="lifecycle", name="Lifecycle")
    project = AIProject.objects.create(organization=organization, slug="p", name="P")
    scenario = Scenario.objects.create(project=project, slug="s", name="S")
    ScenarioAlias.objects.create(scenario=scenario, alias="scenario")
    ScenarioRelease.objects.create(
        scenario=scenario,
        status=ReleaseStatus.ACTIVE,
        runtime_version="runtime:1",
        manifest={},
        artifact_manifest_sha256="a" * 64,
        created_by="seed",
    )
    user = User.objects.create_user("manager", password="unused")  # noqa: S106
    membership = OrganizationMembership.objects.create(organization=organization, user=user)
    ScenarioResponsibilityAssignment.objects.create(
        organization=organization,
        membership=membership,
        scenario=scenario,
        responsibility=responsibility,
        assigned_by=user,
    )
    return scenario, user


@pytest.mark.django_db
def test_release_manager_activates_disables_and_replays_safely() -> None:
    scenario, user = _fixture()

    activated = activate_scenario(scenario, actor=user, request_id="req-activate")
    assert activated.status == LifecycleStatus.ACTIVE
    replayed = activate_scenario(scenario, actor=user, request_id="req-replay")
    assert replayed.status == LifecycleStatus.ACTIVE
    disabled = disable_scenario(scenario, actor=user, request_id="req-disable")
    assert disabled.status == LifecycleStatus.DISABLED

    assert list(
        AuditEvent.objects.filter(action="scenario.activate").values_list("reason", flat=True)
    ) == ["ALREADY_IN_TARGET_STATE", "TRANSITIONED"]
    assert AuditEvent.objects.filter(
        action="scenario.disable", outcome="success", reason="TRANSITIONED"
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "responsibility",
    [
        ScenarioResponsibility.VIEWER,
        ScenarioResponsibility.EDITOR,
        ScenarioResponsibility.RUNTIME_OPERATOR,
        ScenarioResponsibility.APPROVER,
    ],
)
def test_neighboring_scenario_responsibilities_are_denied(responsibility: str) -> None:
    scenario, user = _fixture(responsibility=responsibility)

    with pytest.raises(ScenarioLifecycleError, match="SCENARIO_LIFECYCLE_FORBIDDEN"):
        activate_scenario(scenario, actor=user)

    scenario.refresh_from_db()
    assert scenario.status == LifecycleStatus.DRAFT
    assert AuditEvent.objects.filter(
        action="scenario.activate", outcome="deny", reason="CAPABILITY_NOT_GRANTED"
    ).exists()


@pytest.mark.django_db
def test_activation_requires_active_release_and_alias() -> None:
    scenario, user = _fixture()
    scenario.releases.update(status=ReleaseStatus.SUPERSEDED)

    with pytest.raises(ScenarioLifecycleError, match="ACTIVE_RELEASE_REQUIRED"):
        activate_scenario(scenario, actor=user)
    assert AuditEvent.objects.filter(
        action="scenario.activate", outcome="failure", reason="ACTIVE_RELEASE_REQUIRED"
    ).exists()

    scenario.releases.update(status=ReleaseStatus.ACTIVE)
    scenario.aliases.update(status="closed")
    with pytest.raises(ScenarioLifecycleError, match="ACTIVE_ALIAS_REQUIRED"):
        activate_scenario(scenario, actor=user)


@pytest.mark.django_db
def test_same_tenant_other_scenario_authority_does_not_apply() -> None:
    scenario, user = _fixture()
    other = Scenario.objects.create(project=scenario.project, slug="other", name="Other")
    ScenarioAlias.objects.create(scenario=other, alias="other")
    ScenarioRelease.objects.create(
        scenario=other,
        status=ReleaseStatus.ACTIVE,
        runtime_version="runtime:1",
        manifest={},
        artifact_manifest_sha256="b" * 64,
        created_by="seed",
    )

    with pytest.raises(ScenarioLifecycleError, match="SCENARIO_LIFECYCLE_FORBIDDEN"):
        activate_scenario(other, actor=user)
    other.refresh_from_db()
    assert other.status == LifecycleStatus.DRAFT


@pytest.mark.django_db
def test_activation_requires_exact_release_index_pin_to_be_served() -> None:
    scenario, user = _fixture()
    document_set = DocumentSet.objects.create(
        organization=scenario.organization, logical_id="kb", name="KB"
    )
    set_version = DocumentSetVersion.objects.create(
        organization=scenario.organization,
        document_set=document_set,
        version=1,
        status=DocumentSetVersionStatus.PROMOTABLE,
    )
    index = IndexVersion.objects.create(
        organization=scenario.organization,
        document_set_version=set_version,
        version=1,
        status=IndexStatus.PROMOTABLE,
        store_ready=True,
        dimensions=64,
        index_type="vector",
    )
    scenario.releases.update(manifest={"index_versions": [index.pk]})

    with pytest.raises(ScenarioLifecycleError, match="RELEASE_INDEX_NOT_SERVED"):
        activate_scenario(scenario, actor=user)

    from apps.ingestion.staged_build import promote_staged_index

    promote_staged_index(index, actor="manager")
    activated = activate_scenario(scenario, actor=user)
    assert activated.status == LifecycleStatus.ACTIVE
