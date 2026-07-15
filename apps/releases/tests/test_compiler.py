"""Release compiler behavior and the single-active-release invariant."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.catalog.models import AIProject, Scenario, ScenarioType
from apps.releases.compiler import ArtifactRef, CompileError, compile_release, promote_release
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization

INPUT_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {"query": {"type": "string"}},
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
    "additionalProperties": False,
}


@pytest.fixture
def scenario(db) -> Scenario:
    org = Organization.objects.create(slug="mcm", name="MCM")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    return Scenario.objects.create(project=project, slug="info", name="Info", type=ScenarioType.RAG)


def _seed_contracts(org: Organization) -> None:
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.INPUT_CONTRACT,
        logical_id="customer_query",
        body=INPUT_SCHEMA,
        created_by="alice",
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.OUTPUT_CONTRACT,
        logical_id="customer_answer",
        body=OUTPUT_SCHEMA,
        created_by="alice",
    )


def _refs() -> list[ArtifactRef]:
    return [
        ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "customer_query", 1),
        ArtifactRef("output_contract", ArtifactType.OUTPUT_CONTRACT, "customer_answer", 1),
    ]


@pytest.mark.django_db
def test_compile_happy_path_is_deterministic(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)

    r1 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    r2 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )

    assert r1.status == ReleaseStatus.CANDIDATE
    assert r1.manifest["artifacts"]["input_contract"]["ref"] == "customer_query:v1"
    # Same inputs -> same manifest checksum.
    assert r1.artifact_manifest_sha256 == r2.artifact_manifest_sha256


@pytest.mark.django_db
def test_compile_fails_on_missing_reference(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)
    refs = [ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "customer_query", 99)]
    with pytest.raises(CompileError, match="unresolved reference"):
        compile_release(
            scenario=scenario, refs=refs, runtime_version="rt:3.0.0", created_by="alice"
        )
    assert ScenarioRelease.objects.count() == 0  # no candidate created


@pytest.mark.django_db
def test_compile_rejects_role_type_confusion(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)
    with pytest.raises(CompileError, match="incompatible"):
        compile_release(
            scenario=scenario,
            refs=[ArtifactRef("output_contract", ArtifactType.INPUT_CONTRACT, "customer_query", 1)],
            runtime_version="rt:3.0.0",
            created_by="alice",
        )
    assert ScenarioRelease.objects.count() == 0


@pytest.mark.django_db
def test_compile_fails_on_inline_secret_in_pinned_body(scenario: Scenario) -> None:
    org = scenario.project.organization
    # Bypass the service to plant a secret-bearing artifact, then compile.
    secret_body = {"token": "abc123"}
    ArtifactVersion.objects.create(
        organization=org,
        type=ArtifactType.MODEL_PROFILE,
        logical_id="chat",
        version=1,
        body=secret_body,
        checksum=compute_checksum(secret_body),
        created_by="x",
    )
    refs = [ArtifactRef("model_profile", ArtifactType.MODEL_PROFILE, "chat", 1)]
    with pytest.raises(CompileError, match="validation"):
        compile_release(
            scenario=scenario, refs=refs, runtime_version="rt:3.0.0", created_by="alice"
        )


@pytest.mark.django_db
def test_single_active_release_constraint(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)
    r1 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    r2 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    promote_release(r1)

    r2.status = ReleaseStatus.ACTIVE
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            r2.save()


@pytest.mark.django_db
def test_promote_supersedes_previous_active(scenario: Scenario) -> None:
    _seed_contracts(scenario.project.organization)
    r1 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    r2 = compile_release(
        scenario=scenario, refs=_refs(), runtime_version="rt:3.0.0", created_by="alice"
    )
    promote_release(r1)
    promote_release(r2)

    r1.refresh_from_db()
    r2.refresh_from_db()
    assert r1.status == ReleaseStatus.SUPERSEDED
    assert r2.status == ReleaseStatus.ACTIVE
    active = ScenarioRelease.objects.filter(scenario=scenario, status=ReleaseStatus.ACTIVE)
    assert active.count() == 1
