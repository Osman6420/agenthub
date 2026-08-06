"""Deterministic canonical contract defaults prepared with every new scenario.

A scenario is unusable until an exact input/output contract exists, so the console
prepares both as immutable v1 artifacts at creation time instead of asking the author to
select or hand-write them. The bodies are canonical, not permissive: they describe exactly
the runtime envelope every builtin preset produces (``{"query": ...}`` in,
``{"answer": ..., "sources": [...]}`` out). Widening them is an explicit, audited override.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.services import record_event
from apps.catalog.models import Scenario

# The gateway degrades to a query-only payload when the pinned schema rejects chat history,
# so a closed default stays compatible with the OpenAI-compatible path.
_INPUT_CONTRACT_BODY: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["query"],
    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 4000}},
    "additionalProperties": False,
}

# ``format_output``, ``generate`` and ``agent_loop`` all write exactly this envelope.
_OUTPUT_CONTRACT_BODY: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["answer", "sources"],
    "properties": {"answer": {"type": "string"}, "sources": {"type": "array"}},
    "additionalProperties": False,
}

DEFAULT_CONTRACT_BODIES: dict[str, dict[str, Any]] = {
    ArtifactType.INPUT_CONTRACT: _INPUT_CONTRACT_BODY,
    ArtifactType.OUTPUT_CONTRACT: _OUTPUT_CONTRACT_BODY,
}


def scenario_artifact_logical_id(scenario: Scenario, artifact_type: str) -> str:
    """Return the exact scenario-scoped logical id used for guided release inputs."""

    return f"scenario-{scenario.public_id.hex}-{artifact_type}"


def default_contract_body(artifact_type: str) -> dict[str, Any]:
    """Return a mutable copy of the canonical default body for one contract type."""

    return deepcopy(DEFAULT_CONTRACT_BODIES[artifact_type])


def prepare_scenario_contract_defaults(
    *, scenario: Scenario, actor: str, request_id: str = ""
) -> list[ArtifactVersion]:
    """Create the canonical input/output contract v1 for a scenario that has none.

    Idempotent: an existing logical artifact is left untouched so a re-run never produces a
    surprise version and never overwrites an author's override.
    """

    prepared: list[ArtifactVersion] = []
    for artifact_type in (ArtifactType.INPUT_CONTRACT, ArtifactType.OUTPUT_CONTRACT):
        logical_id = scenario_artifact_logical_id(scenario, artifact_type)
        if ArtifactVersion.objects.filter(
            organization_id=scenario.organization_id,
            type=artifact_type,
            logical_id=logical_id,
        ).exists():
            continue
        artifact = create_artifact_version(
            organization=scenario.organization,
            artifact_type=artifact_type,
            logical_id=logical_id,
            logical_description=f"{scenario.name} canonical {artifact_type}",
            version_description="Scenario default prepared at creation",
            body=default_contract_body(artifact_type),
            created_by=actor,
        )
        record_event(
            actor_type="user",
            actor_id=actor,
            action="console.scenario.contract_default.prepare",
            outcome="success",
            organization_id=scenario.organization_id,
            resource_type=artifact.type,
            resource_id=artifact.ref,
            reason=artifact.checksum,
            request_id=request_id,
            after={"scenario_id": str(scenario.public_id)},
        )
        prepared.append(artifact)
    return prepared
