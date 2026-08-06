from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.builder import services
from apps.builder.models import ArtifactDraft
from apps.builder.tests.conftest import BuilderFixture
from apps.releases.authoring import analyze_workflow_requirements
from apps.releases.models import ReleaseStatus, ScenarioRelease

pytestmark = pytest.mark.django_db


def _workflow(*, primary_config: dict | None = None) -> dict:
    primary: dict = {"id": "primary", "type": "retrieve"}
    if primary_config is not None:
        primary["config"] = primary_config
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "two_retrieve"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                primary,
                {"id": "secondary", "type": "retrieve"},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "primary"},
                {"from": "primary", "to": "secondary"},
                {"from": "secondary", "to": "done"},
            ],
        },
    }


def _profile_body(*, mode: str = "hybrid", top_k: int = 8) -> dict:
    body: dict = {
        "api_version": "agenthub/retrieval/v1",
        "kind": "RetrievalProfile",
        "mode": mode,
        "top_k": top_k,
        "score_threshold": 0,
    }
    if mode == "hybrid":
        body["vector_weight"] = 0.7
        body["keyword_weight"] = 0.3
    return body


def test_two_retrieve_nodes_publish_independent_roles_and_reuse_unchanged_versions(
    bf: BuilderFixture,
) -> None:
    bf.draft.body = _workflow()
    bf.draft.save(update_fields=["body"])

    primary = services.save_retrieve_node_binding(
        bf.draft,
        actor="author",
        expected_revision=1,
        workflow_body=bf.draft.body,
        node_id="primary",
        profile_body=_profile_body(top_k=4),
    )
    secondary = services.save_retrieve_node_binding(
        primary,
        actor="author",
        expected_revision=2,
        workflow_body=primary.body,
        node_id="secondary",
        profile_body=_profile_body(mode="keyword", top_k=12),
    )
    primary_ref = secondary.body["spec"]["nodes"][1]["config"]["retrieval_profile_ref"]
    secondary_ref = secondary.body["spec"]["nodes"][2]["config"]["retrieval_profile_ref"]
    assert primary_ref != secondary_ref
    assert all(ref.startswith("ret_") and len(ref) <= 64 for ref in (primary_ref, secondary_ref))

    workflow_v1 = services.publish_draft(
        secondary, actor="author", expected_revision=3, version_description="Retrieve bindings"
    )
    requirements = analyze_workflow_requirements(
        scenario=bf.scenario, workflow_artifact_id=workflow_v1.pk
    )["requirements"]
    assert {(item["role"], item["artifact_type"]) for item in requirements} >= {
        (primary_ref, ArtifactType.RETRIEVAL_PROFILE),
        (secondary_ref, ArtifactType.RETRIEVAL_PROFILE),
    }
    assert ArtifactVersion.objects.exclude(type=ArtifactType.WORKFLOW_DEFINITION).count() == 2

    # An unchanged body republishes nothing: immutable versions are never duplicated.
    services.publish_draft(
        secondary, actor="author", expected_revision=4, version_description="Workflow only"
    )
    assert ArtifactVersion.objects.exclude(type=ArtifactType.WORKFLOW_DEFINITION).count() == 2

    secondary.refresh_from_db()
    changed = services.save_retrieve_node_binding(
        secondary,
        actor="author",
        expected_revision=5,
        workflow_body=secondary.body,
        node_id="primary",
        profile_body=_profile_body(top_k=9),
    )
    services.publish_draft(
        changed,
        actor="author",
        expected_revision=6,
        version_description="Primary retrieval changed",
    )
    assert (
        ArtifactVersion.objects.filter(
            type=ArtifactType.RETRIEVAL_PROFILE, logical_id=primary_ref
        ).count()
        == 2
    )
    assert (
        ArtifactVersion.objects.filter(
            type=ArtifactType.RETRIEVAL_PROFILE, logical_id=secondary_ref
        ).count()
        == 1
    )


def test_legacy_retrieve_refs_are_required_but_never_auto_published(bf: BuilderFixture) -> None:
    """A custom/legacy role stays release-manager pinned; the builder must not version it."""

    bf.draft.body = _workflow(primary_config={"retrieval_profile_ref": "legacy_support_profile"})
    bf.draft.save(update_fields=["body"])

    workflow_v1 = services.publish_draft(
        bf.draft, actor="author", expected_revision=1, version_description="Legacy ref"
    )
    requirements = analyze_workflow_requirements(
        scenario=bf.scenario, workflow_artifact_id=workflow_v1.pk
    )["requirements"]
    assert ("legacy_support_profile", ArtifactType.RETRIEVAL_PROFILE) in {
        (item["role"], item["artifact_type"]) for item in requirements
    }
    # The unbound ``secondary`` node keeps the release-level fallback and adds no requirement.
    assert not any(
        item["artifact_type"] == ArtifactType.RETRIEVAL_PROFILE
        and item["role"] != "legacy_support_profile"
        for item in requirements
    )
    assert not ArtifactVersion.objects.filter(type=ArtifactType.RETRIEVAL_PROFILE).exists()


def test_retrieve_binding_seeds_from_active_release_until_the_node_is_bound(
    bf: BuilderFixture,
) -> None:
    bf.draft.body = _workflow()
    bf.draft.save(update_fields=["body"])
    release_body = _profile_body(mode="vector", top_k=20)
    create_artifact_version(
        organization=bf.org,
        artifact_type=ArtifactType.RETRIEVAL_PROFILE,
        logical_id="release_retrieval",
        logical_description="Release-level retrieval profile",
        version_description="v1",
        body=release_body,
        created_by="release-manager",
    )
    ScenarioRelease.objects.create(
        scenario=bf.scenario,
        status=ReleaseStatus.ACTIVE,
        runtime_version="test",
        manifest={
            "artifacts": {
                "retrieval_profile": {
                    "ref": "release_retrieval:v1",
                    "type": ArtifactType.RETRIEVAL_PROFILE,
                }
            }
        },
        artifact_manifest_sha256="0" * 64,
        created_by="release-manager",
    )

    seeded = services.get_retrieve_node_binding(bf.draft, node_id="primary")
    assert seeded["profile_body"] == release_body
    assert seeded["configured"] is False

    bound = services.save_retrieve_node_binding(
        bf.draft,
        actor="author",
        expected_revision=1,
        workflow_body=bf.draft.body,
        node_id="primary",
        profile_body=_profile_body(top_k=3),
    )
    node_bound = services.get_retrieve_node_binding(bound, node_id="primary")
    assert node_bound["profile_body"]["top_k"] == 3
    assert node_bound["configured"] is True
    # The sibling node is untouched and still reads the release-level profile.
    assert services.get_retrieve_node_binding(bound, node_id="secondary") == seeded | {
        "node_id": "secondary"
    }


def test_retrieve_binding_api_enforces_scope_author_revision_and_validation(
    client: Client, bf: BuilderFixture
) -> None:
    bf.draft.body = _workflow()
    bf.draft.save(update_fields=["body"])
    url = reverse("builder_api:retrieve_node_binding", args=[bf.draft.pk, "primary"])

    client.force_login(bf.outsider)
    assert client.get(url).status_code == 404
    assert (
        client.put(
            url,
            data=json.dumps(
                {"revision": 1, "workflow_body": _workflow(), "profile_body": _profile_body()}
            ),
            content_type="application/json",
        ).status_code
        == 404
    )

    client.force_login(bf.viewer)
    viewer_get = client.get(url)
    assert viewer_get.status_code == 200
    assert viewer_get.json()["can_write"] is False
    denied = client.put(
        url,
        data=json.dumps(
            {"revision": 1, "workflow_body": _workflow(), "profile_body": _profile_body()}
        ),
        content_type="application/json",
    )
    assert denied.status_code == 403

    client.force_login(bf.author)
    stale = client.put(
        url,
        data=json.dumps(
            {"revision": 99, "workflow_body": _workflow(), "profile_body": _profile_body()}
        ),
        content_type="application/json",
    )
    assert stale.status_code == 409
    invalid = client.put(
        url,
        data=json.dumps(
            {
                "revision": 1,
                "workflow_body": _workflow(),
                "profile_body": _profile_body(top_k=500),
            }
        ),
        content_type="application/json",
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "candidate_invalid_artifact"
    assert not ArtifactDraft.objects.exists()

    saved = client.put(
        url,
        data=json.dumps(
            {"revision": 1, "workflow_body": _workflow(), "profile_body": _profile_body(top_k=6)}
        ),
        content_type="application/json",
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["draft"]["revision"] == 2
    assert payload["binding"]["configured"] is True
    assert payload["binding"]["profile_body"]["top_k"] == 6
    node_config = payload["draft"]["body"]["spec"]["nodes"][1]["config"]
    assert node_config["retrieval_profile_ref"].startswith("ret_")
    # The node id is never a manifest role and the profile body carries no platform secret.
    assert node_config["retrieval_profile_ref"] != "primary"
