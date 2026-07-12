"""Gated promotion, index-readiness gate, rollback, and release-manager auth."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.catalog.models import AIProject, Scenario, ScenarioType
from apps.evaluations.services import run_eval
from apps.identity.models import Consumer
from apps.identity.roles import Role
from apps.ingestion.models import IndexStatus, IndexVersion, Source
from apps.orchestration.resolver import resolve_bundle
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.lifecycle import (
    LifecycleError,
    promote,
    rollback,
    start_canary,
    stop_canary,
)
from apps.releases.models import CanaryStatus, ReleaseStatus, ScenarioRelease
from apps.releases.routing import select_release
from apps.retrieval.providers import StaticRetrievalProvider
from apps.retrieval.types import RetrievedChunk
from apps.tenancy.models import Organization, OrganizationMembership
from apps.tenancy.services import can_manage_releases

CHUNK = RetrievedChunk(
    text="Iade suresi 14 gundur.",
    source_id="mcm",
    source_uri="https://x/iade",
    title="Iade",
    score=0.9,
)
PASSING_SUITE = {
    "cases": [{"id": "c1", "input": {"query": "iade"}, "assertions": [{"type": "grounded"}]}]
}


def _scenario() -> Scenario:
    org = Organization.objects.create(slug="mcm", name="MCM")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    return Scenario.objects.create(project=project, slug="info", name="Info", type=ScenarioType.RAG)


def _release(
    scenario: Scenario, *, with_suite: bool = True, index_versions: list[int] | None = None
):
    org = scenario.project.organization
    refs: list[ArtifactRef] = []
    if with_suite:
        # A fresh suite per release keeps checksums independent across releases.
        logical = f"suite_{ScenarioRelease.objects.count()}"
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.EVAL_SUITE,
            logical_id=logical,
            body=PASSING_SUITE,
            created_by="alice",
        )
        refs.append(ArtifactRef("eval_suite", ArtifactType.EVAL_SUITE, logical, 1))
    else:
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.MODEL_PROFILE,
            logical_id="chat",
            body={"profile_id": "00000000-0000-0000-0000-000000000001"},
            created_by="alice",
        )
        refs.append(ArtifactRef("model_profile", ArtifactType.MODEL_PROFILE, "chat", 1))
    return compile_release(
        scenario=scenario,
        refs=refs,
        runtime_version="rt:3.0.0",
        created_by="alice",
        index_versions=index_versions,
    )


def _pass_eval(release: ScenarioRelease) -> None:
    run_eval(
        release=release, created_by="alice", retrieval_provider=StaticRetrievalProvider([CHUNK])
    )


@pytest.mark.django_db
def test_promotion_without_eval_is_denied_and_audited() -> None:
    release = _release(_scenario())
    with pytest.raises(LifecycleError, match="EVAL_REQUIRED"):
        promote(release=release, actor="alice")
    release.refresh_from_db()
    assert release.status == ReleaseStatus.CANDIDATE
    assert AuditEvent.objects.filter(
        action="release.promote", outcome="deny", reason="EVAL_REQUIRED"
    ).exists()


@pytest.mark.django_db
def test_promotion_without_pinned_suite_is_denied() -> None:
    release = _release(_scenario(), with_suite=False)
    with pytest.raises(LifecycleError, match="EVAL_SUITE_NOT_PINNED"):
        promote(release=release, actor="alice")


@pytest.mark.django_db
def test_passing_eval_allows_promotion_and_supersedes_previous() -> None:
    scenario = _scenario()
    r1 = _release(scenario)
    _pass_eval(r1)
    promote(release=r1, actor="alice")
    r1.refresh_from_db()
    assert r1.status == ReleaseStatus.ACTIVE

    r2 = _release(scenario)
    _pass_eval(r2)
    promote(release=r2, actor="alice")

    r1.refresh_from_db()
    r2.refresh_from_db()
    assert r1.status == ReleaseStatus.SUPERSEDED
    assert r2.status == ReleaseStatus.ACTIVE
    assert (
        ScenarioRelease.objects.filter(scenario=scenario, status=ReleaseStatus.ACTIVE).count() == 1
    )


@pytest.mark.django_db
def test_promotion_blocked_when_pinned_index_not_ready() -> None:
    release = _release(_scenario(), index_versions=[999999])
    _pass_eval(release)
    with pytest.raises(LifecycleError, match="INDEX_NOT_READY"):
        promote(release=release, actor="alice")
    assert AuditEvent.objects.filter(
        action="release.promote", outcome="deny", reason="INDEX_NOT_READY"
    ).exists()


@pytest.mark.django_db
def test_promotion_succeeds_with_ready_tenant_index() -> None:
    scenario = _scenario()
    org = scenario.project.organization
    source = Source.objects.create(
        organization=org, slug="docs", name="Docs", connector_type="https"
    )
    index = IndexVersion.objects.create(
        organization=org, source=source, version=1, status=IndexStatus.PROMOTABLE
    )
    release = _release(scenario, index_versions=[index.pk])
    _pass_eval(release)
    promote(release=release, actor="alice")
    release.refresh_from_db()
    assert release.status == ReleaseStatus.ACTIVE
    # The pin is now reachable end-to-end through the resolver.
    assert resolve_bundle(release).index_versions == [index.pk]


@pytest.mark.django_db
def test_rollback_restores_a_superseded_release() -> None:
    scenario = _scenario()
    r1 = _release(scenario)
    _pass_eval(r1)
    promote(release=r1, actor="alice")
    r2 = _release(scenario)
    _pass_eval(r2)
    promote(release=r2, actor="alice")  # r1 -> superseded, r2 -> active

    restored = rollback(scenario=scenario, target=r1, actor="alice")

    assert restored.pk == r1.pk and restored.status == ReleaseStatus.ACTIVE
    r2.refresh_from_db()
    assert r2.status == ReleaseStatus.ROLLED_BACK
    assert (
        ScenarioRelease.objects.filter(scenario=scenario, status=ReleaseStatus.ACTIVE).count() == 1
    )
    assert AuditEvent.objects.filter(action="release.rollback", outcome="allow").exists()


@pytest.mark.django_db
def test_rollback_rejects_non_superseded_target() -> None:
    scenario = _scenario()
    r1 = _release(scenario)  # still a candidate
    with pytest.raises(LifecycleError, match="TARGET_NOT_ROLLBACKABLE"):
        rollback(scenario=scenario, target=r1, actor="alice")


@pytest.mark.django_db
def test_can_manage_releases_requires_release_manager_role() -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    user_model = get_user_model()
    manager = user_model.objects.create_user(username="rm", password="x")  # noqa: S106
    stranger = user_model.objects.create_user(username="ns", password="x")  # noqa: S106
    OrganizationMembership.objects.create(organization=org, user=manager, role=Role.RELEASE_MANAGER)
    OrganizationMembership.objects.create(organization=org, user=stranger, role=Role.AUDITOR)

    assert can_manage_releases(manager, org.pk) is True
    assert can_manage_releases(stranger, org.pk) is False


def _consumer(scenario: Scenario, subject: str) -> Consumer:
    return Consumer.objects.create(
        organization=scenario.project.organization, subject=subject, name=subject, protocol="rest"
    )


@pytest.mark.django_db
def test_canary_routes_only_the_assigned_consumer() -> None:
    scenario = _scenario()
    assigned = _consumer(scenario, "assigned")
    other = _consumer(scenario, "other")
    active = _release(scenario)
    _pass_eval(active)
    promote(release=active, actor="alice")

    candidate = _release(scenario)
    _pass_eval(candidate)
    start_canary(release=candidate, consumer=assigned, ttl_seconds=3600, actor="alice")

    candidate.refresh_from_db()
    assert candidate.status == ReleaseStatus.CANARY

    rel, is_canary = select_release(scenario=scenario, consumer=assigned)
    assert is_canary is True
    assert rel is not None and rel.pk == candidate.pk
    rel2, is_canary2 = select_release(scenario=scenario, consumer=other)
    assert is_canary2 is False
    assert rel2 is not None and rel2.pk == active.pk


@pytest.mark.django_db
def test_canary_requires_passing_eval() -> None:
    scenario = _scenario()
    consumer = _consumer(scenario, "c1")
    candidate = _release(scenario)  # no eval
    with pytest.raises(LifecycleError, match="EVAL_REQUIRED"):
        start_canary(release=candidate, consumer=consumer, ttl_seconds=3600, actor="alice")


@pytest.mark.django_db
def test_canary_rejects_cross_tenant_consumer() -> None:
    scenario = _scenario()
    other_org = Organization.objects.create(slug="other", name="Other")
    foreign = Consumer.objects.create(
        organization=other_org, subject="x", name="x", protocol="rest"
    )
    candidate = _release(scenario)
    _pass_eval(candidate)
    with pytest.raises(LifecycleError, match="CANARY_CROSS_TENANT"):
        start_canary(release=candidate, consumer=foreign, ttl_seconds=3600, actor="alice")


@pytest.mark.django_db
def test_expired_canary_falls_back_to_active() -> None:
    scenario = _scenario()
    consumer = _consumer(scenario, "c1")
    active = _release(scenario)
    _pass_eval(active)
    promote(release=active, actor="alice")
    candidate = _release(scenario)
    _pass_eval(candidate)
    canary = start_canary(release=candidate, consumer=consumer, ttl_seconds=3600, actor="alice")

    canary.expires_at = timezone.now() - timedelta(seconds=1)
    canary.save(update_fields=["expires_at"])

    rel, is_canary = select_release(scenario=scenario, consumer=consumer)
    assert is_canary is False
    assert rel is not None and rel.pk == active.pk


@pytest.mark.django_db
def test_stop_canary_reverts_release_to_candidate() -> None:
    scenario = _scenario()
    consumer = _consumer(scenario, "c1")
    candidate = _release(scenario)
    _pass_eval(candidate)
    canary = start_canary(release=candidate, consumer=consumer, ttl_seconds=3600, actor="alice")

    stopped = stop_canary(canary=canary, actor="alice")

    assert stopped.status == CanaryStatus.STOPPED
    candidate.refresh_from_db()
    assert candidate.status == ReleaseStatus.CANDIDATE
    _, is_canary = select_release(scenario=scenario, consumer=consumer)
    assert is_canary is False
