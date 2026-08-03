from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.builder import services
from apps.builder.models import ArtifactDraft
from apps.builder.tests.conftest import BuilderFixture
from apps.orchestration.models import ModelProfile, ModelProfileStatus
from apps.releases.authoring import analyze_workflow_requirements

pytestmark = pytest.mark.django_db


def _workflow() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "two_generate"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "first", "type": "generate"},
                {"id": "second", "type": "generate"},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "first"},
                {"from": "first", "to": "second"},
                {"from": "second", "to": "done"},
            ],
        },
    }


def _profile(*, status: str = ModelProfileStatus.ACTIVE) -> ModelProfile:
    return ModelProfile.objects.create(
        logical_id=f"generate-{status}",
        revision=1,
        host="model.internal.example",
        model="answer-v1",
        secret_ref="secret://model",  # noqa: S106 -- opaque reference
        status=status,
        created_by="platform-admin",
    )


def test_two_generate_nodes_publish_independent_roles_and_reuse_unchanged_versions(
    bf: BuilderFixture,
) -> None:
    profile = _profile()
    bf.draft.body = _workflow()
    bf.draft.save(update_fields=["body"])

    first = services.save_generate_node_binding(
        bf.draft,
        actor="author",
        expected_revision=1,
        workflow_body=bf.draft.body,
        node_id="first",
        prompt_text="İlk prompt",
        model_profile_id=str(profile.public_id),
    )
    second = services.save_generate_node_binding(
        first,
        actor="author",
        expected_revision=2,
        workflow_body=first.body,
        node_id="second",
        prompt_text="İkinci prompt",
        model_profile_id=str(profile.public_id),
    )
    first_config = second.body["spec"]["nodes"][1]["config"]
    second_config = second.body["spec"]["nodes"][2]["config"]
    assert first_config["prompt_ref"] != second_config["prompt_ref"]
    assert first_config["model_profile_ref"] != second_config["model_profile_ref"]
    assert all(len(value) <= 64 for value in [*first_config.values(), *second_config.values()])

    workflow_v1 = services.publish_draft(
        second, actor="author", expected_revision=3, version_description="Generate bindings"
    )
    requirements = analyze_workflow_requirements(
        scenario=bf.scenario, workflow_artifact_id=workflow_v1.pk
    )["requirements"]
    assert {(item["role"], item["artifact_type"]) for item in requirements} >= {
        (first_config["prompt_ref"], ArtifactType.PROMPT_TEMPLATE),
        (first_config["model_profile_ref"], ArtifactType.MODEL_PROFILE),
        (second_config["prompt_ref"], ArtifactType.PROMPT_TEMPLATE),
        (second_config["model_profile_ref"], ArtifactType.MODEL_PROFILE),
    }
    assert ArtifactVersion.objects.exclude(type=ArtifactType.WORKFLOW_DEFINITION).count() == 4

    services.publish_draft(
        second, actor="author", expected_revision=4, version_description="Workflow only"
    )
    assert ArtifactVersion.objects.exclude(type=ArtifactType.WORKFLOW_DEFINITION).count() == 4

    second.refresh_from_db()
    changed = services.save_generate_node_binding(
        second,
        actor="author",
        expected_revision=5,
        workflow_body=second.body,
        node_id="first",
        prompt_text="İlk prompt değişti",
        model_profile_id=str(profile.public_id),
    )
    services.publish_draft(
        changed, actor="author", expected_revision=6, version_description="Prompt changed"
    )
    assert (
        ArtifactVersion.objects.filter(
            type=ArtifactType.PROMPT_TEMPLATE, logical_id=first_config["prompt_ref"]
        ).count()
        == 2
    )
    assert (
        ArtifactVersion.objects.filter(
            type=ArtifactType.MODEL_PROFILE, logical_id=first_config["model_profile_ref"]
        ).count()
        == 1
    )


def test_generate_binding_api_enforces_author_revision_and_active_model(
    client: Client, bf: BuilderFixture
) -> None:
    profile = _profile()
    inactive = _profile(status=ModelProfileStatus.DISABLED)
    bf.draft.body = _workflow()
    bf.draft.save(update_fields=["body"])
    url = reverse("builder_api:generate_node_binding", args=[bf.draft.pk, "first"])

    client.force_login(bf.outsider)
    assert client.get(url).status_code == 404
    client.force_login(bf.viewer)
    assert client.get(url).status_code == 200
    denied = client.put(
        url,
        data=json.dumps(
            {
                "revision": 1,
                "workflow_body": _workflow(),
                "prompt_text": "Viewer prompt",
                "model_profile_id": str(profile.public_id),
            }
        ),
        content_type="application/json",
    )
    assert denied.status_code == 403

    client.force_login(bf.author)
    stale = client.put(
        url,
        data=json.dumps(
            {
                "revision": 99,
                "workflow_body": _workflow(),
                "prompt_text": "Prompt",
                "model_profile_id": str(profile.public_id),
            }
        ),
        content_type="application/json",
    )
    assert stale.status_code == 409
    inactive_response = client.put(
        url,
        data=json.dumps(
            {
                "revision": 1,
                "workflow_body": _workflow(),
                "prompt_text": "Prompt",
                "model_profile_id": str(inactive.public_id),
            }
        ),
        content_type="application/json",
    )
    assert inactive_response.status_code == 400
    assert inactive_response.json()["error"]["code"] == "model_profile_unavailable"
    assert not ArtifactDraft.objects.exists()

    saved = client.put(
        url,
        data=json.dumps(
            {
                "revision": 1,
                "workflow_body": _workflow(),
                "prompt_text": "Prompt",
                "model_profile_id": str(profile.public_id),
            }
        ),
        content_type="application/json",
    )
    assert saved.status_code == 200
    assert saved.json()["draft"]["revision"] == 2
    assert saved.json()["binding"]["prompt_text"] == "Prompt"
    assert "prompt_ref" in saved.json()["draft"]["body"]["spec"]["nodes"][1]["config"]
