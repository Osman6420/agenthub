"""Deterministic naming for the scenario-owned artifacts a release pins.

A scenario owns a small set of artifacts that are not workflow-node derived: its
input/output contracts and its evaluation suite. Their logical ids are a pure function of
the scenario's immutable public id, so both the console authoring forms and the release
manifest derivation resolve the same artifact without an operator naming anything.

This lives below ``apps.console`` on purpose: ``apps.releases`` must be able to derive a
manifest without importing the operator console.
"""

from __future__ import annotations

from apps.artifacts.types import ArtifactType
from apps.catalog.models import Scenario

# Manifest roles for scenario-owned artifacts. The role is the artifact type verbatim;
# only the logical id is scenario-scoped.
SCENARIO_SCOPED_ROLES: tuple[str, ...] = (
    ArtifactType.INPUT_CONTRACT,
    ArtifactType.OUTPUT_CONTRACT,
    ArtifactType.EVAL_SUITE,
)


def scenario_artifact_logical_id(scenario: Scenario, artifact_type: str) -> str:
    """Return the exact scenario-scoped logical id used for guided release inputs."""

    return f"scenario-{scenario.public_id.hex}-{artifact_type}"
