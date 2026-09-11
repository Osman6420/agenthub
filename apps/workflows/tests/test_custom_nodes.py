from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import ArtifactValidationError
from apps.tenancy.models import Organization
from apps.workflows.compiler import WorkflowCompileError
from apps.workflows.custom_nodes import execute_custom_node, register_executor, unregister_executor
from apps.workflows.services import register_custom_node_definition


def custom_node_body() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "CustomNode",
        "metadata": {"id": "redact_customer_data.v2", "owner": "data-platform"},
        "spec": {
            "package": "agenthub_nodes.customer_data",
            "package_version": "2.1.0",
            "entrypoint": "agenthub_nodes.customer_data.RedactCustomerDataNode",
            "config_schema_ref": "redact_config:v1",
            "input_state_schema_ref": "redact_input:v1",
            "output_state_schema_ref": "redact_output:v1",
            "allowed_organizations": ["mcm"],
            "execution": {
                "queue": "runtime",
                "timeout_seconds": 5,
                "max_output_bytes": 32768,
            },
            "permissions": {
                "allow_retrieval": False,
                "allow_model_generation": False,
                "allow_tool_calls": False,
            },
        },
    }


@pytest.mark.django_db
def test_custom_node_manifest_is_accepted_as_data_not_uploaded_code() -> None:
    organization = Organization.objects.create(slug="mcm", name="MCM")
    artifact = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.CUSTOM_NODE_DEFINITION,
        logical_id="redact_customer_data",
        body=custom_node_body(),
        created_by="platform-admin",
    )
    assert artifact.body["spec"]["package"] == "agenthub_nodes.customer_data"


@pytest.mark.django_db
def test_custom_node_cannot_enable_direct_tool_calls() -> None:
    organization = Organization.objects.create(slug="mcm", name="MCM")
    body = custom_node_body()
    body["spec"]["permissions"]["allow_tool_calls"] = True
    with pytest.raises(ArtifactValidationError, match="cannot call tools"):
        create_artifact_version(
            organization=organization,
            artifact_type=ArtifactType.CUSTOM_NODE_DEFINITION,
            logical_id="unsafe",
            body=body,
            created_by="platform-admin",
        )


@pytest.mark.django_db
def test_preinstalled_custom_node_is_schema_checked_and_receives_restricted_context() -> None:
    organization = Organization.objects.create(slug="mcm", name="MCM")
    for logical_id, body, artifact_type in (
        (
            "redact_config",
            {
                "type": "object",
                "properties": {"fields": {"type": "array", "items": {"type": "string"}}},
                "required": ["fields"],
                "additionalProperties": False,
            },
            ArtifactType.INPUT_CONTRACT,
        ),
        (
            "redact_input",
            {"type": "object"},
            ArtifactType.INPUT_CONTRACT,
        ),
        (
            "redact_output",
            {
                "type": "object",
                "properties": {"redacted": {"type": "boolean"}},
                "required": ["redacted"],
                "additionalProperties": False,
            },
            ArtifactType.OUTPUT_CONTRACT,
        ),
    ):
        create_artifact_version(
            organization=organization,
            artifact_type=artifact_type,
            logical_id=logical_id,
            body=body,
            created_by="platform-admin",
        )
    artifact = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.CUSTOM_NODE_DEFINITION,
        logical_id="redact_customer_data",
        body=custom_node_body(),
        created_by="platform-admin",
    )
    register_custom_node_definition(artifact=artifact, installed_package_version="2.1.0")
    seen_context: list[object] = []

    def executor(config, state, context):
        seen_context.append(context)
        assert config == {"fields": ["answer"]}
        assert "request" not in vars(context)
        assert "secret" not in vars(context)
        return {"redacted": True}

    register_executor("redact_customer_data.v1", "2.1.0", executor)
    try:
        patch = execute_custom_node(
            node_ref="redact_customer_data.v1",
            config={"fields": ["answer"]},
            state={"output": {"answer": "[redacted]"}},
            run=SimpleNamespace(
                organization=organization,
                organization_id=organization.id,
                scenario_id=11,
                release_id=12,
                id=13,
            ),
        )
    finally:
        unregister_executor("redact_customer_data.v1")
    assert patch == {"redacted": True}
    assert len(seen_context) == 1


@pytest.mark.django_db
def test_custom_node_package_mismatch_fails_closed() -> None:
    organization = Organization.objects.create(slug="mcm", name="MCM")
    artifact = create_artifact_version(
        organization=organization,
        artifact_type=ArtifactType.CUSTOM_NODE_DEFINITION,
        logical_id="redact_customer_data",
        body=custom_node_body(),
        created_by="platform-admin",
    )
    with pytest.raises(WorkflowCompileError, match="package version"):
        register_custom_node_definition(artifact=artifact, installed_package_version="9.9.9")
