"""Shared setup for gateway API tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.identity.tokens import create_token
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.tenancy.models import Organization
from apps.workflows.presets import empty_workflow

INPUT_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {"query": {"type": "string"}},
    "additionalProperties": True,
}


@dataclass
class Fixture:
    organization: Organization
    scenario: Scenario
    alias: str
    consumer: Consumer
    raw_token: str


def build_scenario(
    *,
    capabilities: list[str] | None = None,
    active_release: bool = True,
    with_input_contract: bool = True,
    alias: str = "customer-information",
) -> Fixture:
    org = Organization.objects.create(slug="mcm", name="MCM")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(
        project=project,
        slug="info",
        name="Info",
        status=LifecycleStatus.ACTIVE,
    )
    ScenarioAlias.objects.create(scenario=scenario, alias=alias)
    consumer = Consumer.objects.create(
        organization=org, subject="svc-1", name="Backend", protocol=ConsumerProtocol.REST
    )
    _, raw = create_token(consumer, "test")
    ConsumerBinding.objects.create(
        consumer=consumer,
        scenario=scenario,
        capabilities=capabilities if capabilities is not None else [Capability.WORKFLOW_RUN],
    )

    if with_input_contract:
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.INPUT_CONTRACT,
            logical_id="customer_query",
            body=INPUT_SCHEMA,
            created_by="test",
        )
    if active_release:
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.WORKFLOW_DEFINITION,
            logical_id="customer_workflow",
            body=empty_workflow(logical_id="customer_workflow"),
            created_by="test",
        )
        refs = [
            ArtifactRef(
                "workflow_definition",
                ArtifactType.WORKFLOW_DEFINITION,
                "customer_workflow",
                1,
            )
        ]
        if with_input_contract:
            refs.append(
                ArtifactRef("input_contract", ArtifactType.INPUT_CONTRACT, "customer_query", 1)
            )
        release = compile_release(
            scenario=scenario, refs=refs, runtime_version="rt:3.0.0", created_by="test"
        )
        promote_release(release)

    return Fixture(
        organization=org,
        scenario=scenario,
        alias=alias,
        consumer=consumer,
        raw_token=raw,
    )


@pytest.fixture
def scenario_fixture(db) -> Fixture:
    return build_scenario()
