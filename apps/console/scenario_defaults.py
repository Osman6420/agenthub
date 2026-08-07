"""Deterministic canonical defaults prepared with every new scenario.

A scenario is unusable until an exact input/output contract exists, so the console
prepares both as immutable v1 artifacts at creation time instead of asking the author to
select or hand-write them. The bodies are canonical, not permissive: they describe exactly
the runtime envelope every builtin preset produces (``{"query": ...}`` in,
``{"answer": ..., "sources": [...]}`` out). Widening them is an explicit, audited override.

The evaluation suite is prepared the same way. Before this, ``eval_suite`` was the only
release input with no default, so a first candidate could never pin one: the author had to
compile a candidate, leave to author a suite, return, and compile a *second* candidate
before an evaluation could run at all. A default smoke suite removes that round trip.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.audit.services import record_event
from apps.catalog.models import Scenario
from apps.releases.scenario_artifacts import (
    SCENARIO_SCOPED_ROLES,
    scenario_artifact_logical_id,
)

__all__ = [
    "DEFAULT_CONTRACT_BODIES",
    "default_contract_body",
    "prepare_scenario_contract_defaults",
    "scenario_artifact_logical_id",
]

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

# The narrowest suite that proves the scenario runs end to end: one case, one nullary
# assertion from the closed allowlist in ``apps.artifacts.eval_suite``. It asserts the run
# completed, never what the model said, so it stays meaningful for any workflow shape.
_EVAL_SUITE_BODY: dict[str, Any] = {
    "cases": [
        {
            "id": "smoke-1",
            "input": {"query": "Kontrollü bir test sorusu"},
            "assertions": [{"type": "workflow_completed"}],
        }
    ]
}

DEFAULT_CONTRACT_BODIES: dict[str, dict[str, Any]] = {
    ArtifactType.INPUT_CONTRACT: _INPUT_CONTRACT_BODY,
    ArtifactType.OUTPUT_CONTRACT: _OUTPUT_CONTRACT_BODY,
    ArtifactType.EVAL_SUITE: _EVAL_SUITE_BODY,
}


def default_contract_body(artifact_type: str) -> dict[str, Any]:
    """Return a mutable copy of the canonical default body for one contract type."""

    return deepcopy(DEFAULT_CONTRACT_BODIES[artifact_type])


def prepare_scenario_contract_defaults(
    *, scenario: Scenario, actor: str, request_id: str = ""
) -> list[ArtifactVersion]:
    """Create the canonical scenario-owned release inputs (v1) for a scenario that has none.

    Idempotent: an existing logical artifact is left untouched so a re-run never produces a
    surprise version and never overwrites an author's override. Safe to call again for
    scenarios created before a default was added, which is how existing scenarios acquire
    their evaluation suite.
    """

    prepared: list[ArtifactVersion] = []
    for artifact_type in SCENARIO_SCOPED_ROLES:
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
