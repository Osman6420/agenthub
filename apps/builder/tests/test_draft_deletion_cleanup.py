"""Deleting a workflow draft must not leave its node-owned artifact drafts orphaned."""

from __future__ import annotations

import pytest

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.audit.models import AuditEvent
from apps.builder import services
from apps.builder.models import ArtifactDraft, WorkflowDraft
from apps.builder.tests.conftest import BuilderFixture
from apps.orchestration.models import ModelProfile, ModelProfileStatus

pytestmark = pytest.mark.django_db


def _workflow() -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "cleanup_flow"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "search", "type": "retrieve"},
                {"id": "answer", "type": "generate"},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "search"},
                {"from": "search", "to": "answer"},
                {"from": "answer", "to": "done"},
            ],
        },
    }


def _bound_draft(bf: BuilderFixture) -> WorkflowDraft:
    profile = ModelProfile.objects.create(
        logical_id="cleanup-model",
        revision=1,
        host="model.internal.example",
        model="answer-v1",
        secret_ref="secret://model",  # noqa: S106 -- opaque reference
        status=ModelProfileStatus.ACTIVE,
        created_by="platform-admin",
    )
    bf.draft.body = _workflow()
    bf.draft.save(update_fields=["body"])
    bound = services.save_retrieve_node_binding(
        bf.draft,
        actor="author",
        expected_revision=1,
        workflow_body=bf.draft.body,
        node_id="search",
        profile_body={
            "api_version": "agenthub/retrieval/v1",
            "kind": "RetrievalProfile",
            "mode": "keyword",
            "top_k": 5,
            "score_threshold": 0,
        },
    )
    return services.save_generate_node_binding(
        bound,
        actor="author",
        expected_revision=2,
        workflow_body=bound.body,
        node_id="answer",
        prompt_text="Yanıtla",
        model_profile_id=str(profile.public_id),
    )


def test_deleting_a_workflow_draft_removes_its_node_owned_artifact_drafts(
    bf: BuilderFixture,
) -> None:
    draft = _bound_draft(bf)
    roles = services.node_owned_role_ids(draft)
    assert len(roles) == 3  # one retrieval role plus the generate prompt/model pair
    assert ArtifactDraft.objects.filter(logical_id__in=roles).count() == 3

    services.delete_draft(draft, actor="author", expected_revision=draft.revision)

    assert not WorkflowDraft.objects.filter(pk=draft.pk).exists()
    assert not ArtifactDraft.objects.filter(logical_id__in=roles).exists()
    # Each removal is audited, so the cleanup is not a silent side effect.
    assert AuditEvent.objects.filter(action="console.builder.artifact_draft.delete").count() == 3


def test_deletion_never_touches_published_versions_or_unrelated_drafts(
    bf: BuilderFixture,
) -> None:
    draft = _bound_draft(bf)
    services.publish_draft(
        draft, actor="author", expected_revision=draft.revision, version_description="v1"
    )
    draft.refresh_from_db()
    published = ArtifactVersion.objects.exclude(type=ArtifactType.WORKFLOW_DEFINITION).count()
    assert published == 3

    unrelated = services.create_artifact_draft(
        organization=bf.org,
        project=bf.project,
        scenario=bf.scenario,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        name="Author owned",
        logical_id="author.owned.prompt",
        logical_description="An artifact the author manages directly",
        body={"template": "Kendi promptum"},
        actor="author",
    )

    services.delete_draft(draft, actor="author", expected_revision=draft.revision)

    assert ArtifactVersion.objects.exclude(type=ArtifactType.WORKFLOW_DEFINITION).count() == 3
    assert ArtifactDraft.objects.filter(pk=unrelated.pk).exists()
