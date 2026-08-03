"""Builder service invariants: body bounds, diagnostics parity, publish versioning."""

from __future__ import annotations

import pytest

from apps.artifacts.models import ArtifactVersion
from apps.builder import services
from apps.builder.models import ArtifactDraft, WorkflowDraft
from apps.builder.tests.conftest import BuilderFixture, simple_workflow

pytestmark = pytest.mark.django_db


def test_create_rejects_oversized_body(bf: BuilderFixture) -> None:
    huge = {"blob": "x" * (services.MAX_DRAFT_BODY_BYTES + 1)}
    with pytest.raises(services.BuilderError) as exc:
        services.create_draft(
            organization=bf.org,
            name="big",
            logical_id="flow_big",
            body=huge,
            actor="author",
        )
    assert exc.value.code == "body_too_large"
    assert not WorkflowDraft.objects.filter(logical_id="flow_big").exists()


def test_create_rejects_nonempty_invalid_workflow_but_allows_empty_graph_start(
    bf: BuilderFixture,
) -> None:
    with pytest.raises(services.BuilderError) as exc:
        services.create_draft(
            organization=bf.org,
            name="invalid",
            logical_id="invalid_import",
            body={"kind": "Python"},
            actor="author",
        )
    assert exc.value.code == "candidate_invalid_workflow"
    empty = services.create_draft(
        organization=bf.org,
        name="empty",
        logical_id="empty_graph",
        body={},
        actor="author",
    )
    assert empty.body == {}


def test_diagnose_matches_publish_on_secret(bf: BuilderFixture) -> None:
    body = simple_workflow()
    body["spec"]["nodes"][1]["config"]["password"] = "hunter2literal"  # noqa: S105
    # Diagnostics reject the same inline secret publish would (shared validator).
    assert services.diagnose(body)["ok"] is False


def test_diagnose_ok_for_valid_body(bf: BuilderFixture) -> None:
    result = services.diagnose(simple_workflow())
    assert result["ok"] is True
    assert result["compiled_checksum"]


def test_publish_increments_version(bf: BuilderFixture) -> None:
    first = services.publish_draft(
        bf.draft, actor="author", expected_revision=1, version_description="Initial"
    )
    second = services.publish_draft(
        bf.draft, actor="author", expected_revision=2, version_description="Second"
    )
    assert first.version == 1
    assert second.version == 2
    assert (
        ArtifactVersion.objects.filter(
            organization=bf.org, type="workflow_definition", logical_id="flow_a"
        ).count()
        == 2
    )


def test_publish_is_immutable_source_of_truth(bf: BuilderFixture) -> None:
    # The published artifact checksum is the canonical checksum of the draft body.
    from apps.artifacts.validation import compute_checksum

    artifact = services.publish_draft(
        bf.draft, actor="author", expected_revision=1, version_description="Initial"
    )
    assert artifact.checksum == compute_checksum(bf.draft.body)


def test_prompt_draft_publish_creates_new_immutable_version(bf: BuilderFixture) -> None:
    first = ArtifactVersion.objects.create(
        organization=bf.org,
        type="prompt_template",
        logical_id="answer_prompt",
        logical_description="Stable answer behavior",
        version=1,
        version_description="Initial",
        body={"template": "Old text"},
        checksum="a" * 64,
        created_by="author",
    )
    draft = services.create_artifact_draft(
        organization=bf.org,
        project=bf.project,
        scenario=bf.scenario,
        artifact_type="prompt_template",
        name="Answer prompt",
        logical_id="answer_prompt",
        logical_description="Stable answer behavior",
        body={"template": "New text"},
        actor="author",
    )
    published = services.publish_artifact_draft(
        draft,
        actor="author",
        expected_revision=1,
        version_description="Clarifies answer",
    )
    first.refresh_from_db()
    draft.refresh_from_db()
    assert first.body == {"template": "Old text"}
    assert published.version == 2
    assert published.body == {"template": "New text"}
    assert draft.last_published_version == 2
    assert draft.revision == 2


@pytest.mark.parametrize("logical_id", ["Uppercase", "../prompt", "prompt/name", ".prompt"])
def test_artifact_draft_rejects_unsafe_logical_ids(bf: BuilderFixture, logical_id: str) -> None:
    with pytest.raises(services.BuilderError) as exc:
        services.create_artifact_draft(
            organization=bf.org,
            project=bf.project,
            scenario=bf.scenario,
            artifact_type="prompt_template",
            name="Answer prompt",
            logical_id=logical_id,
            logical_description="Stable answer behavior",
            body={"template": "Text"},
            actor="author",
        )
    assert exc.value.code == "logical_id_invalid"


def test_prompt_publish_requires_version_description(bf: BuilderFixture) -> None:
    draft = services.create_artifact_draft(
        organization=bf.org,
        project=bf.project,
        scenario=bf.scenario,
        artifact_type="prompt_template",
        name="Answer prompt",
        logical_id="answer_prompt",
        logical_description="Stable answer behavior",
        body={"template": "Text"},
        actor="author",
    )
    with pytest.raises(services.BuilderError) as exc:
        services.publish_artifact_draft(
            draft, actor="author", expected_revision=1, version_description=" "
        )
    assert exc.value.code == "version_description_required"
    assert not ArtifactVersion.objects.filter(logical_id="answer_prompt").exists()


def test_prompt_publish_rolls_back_when_audit_fails(
    bf: BuilderFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = services.create_artifact_draft(
        organization=bf.org,
        project=bf.project,
        scenario=bf.scenario,
        artifact_type="prompt_template",
        name="Answer prompt",
        logical_id="answer_prompt",
        logical_description="Stable answer behavior",
        body={"template": "PRIVATE_PROMPT_TEXT"},
        actor="author",
    )

    def fail_audit(**_kwargs) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(services, "record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        services.publish_artifact_draft(
            draft,
            actor="author",
            expected_revision=1,
            version_description="Reviewed prompt",
        )

    draft.refresh_from_db()
    assert draft.revision == 1
    assert draft.last_published_version == 0
    assert not ArtifactVersion.objects.filter(logical_id="answer_prompt").exists()


def test_artifact_draft_create_rolls_back_when_audit_fails(
    bf: BuilderFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_audit(**_kwargs) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(services, "record_event", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        services.create_artifact_draft(
            organization=bf.org,
            project=bf.project,
            scenario=bf.scenario,
            artifact_type="input_contract",
            name="Girdi",
            logical_id="input_v1",
            body={"type": "object"},
            actor="author",
            prompt_contract={"id": "safe", "revision": 1, "checksum": "a" * 64},
        )
    assert not ArtifactDraft.objects.exists()


def test_artifact_draft_rejects_unbounded_prompt_metadata_before_write(
    bf: BuilderFixture,
) -> None:
    with pytest.raises(services.BuilderError, match="prompt_contract_invalid"):
        services.create_artifact_draft(
            organization=bf.org,
            project=bf.project,
            scenario=bf.scenario,
            artifact_type="input_contract",
            name="Girdi",
            logical_id="input_v1",
            body={"type": "object"},
            actor="author",
            prompt_contract={
                "id": "safe",
                "revision": 1,
                "checksum": "not-a-checksum",
                "unexpected": "must-not-reach-audit",
            },
        )
    assert not ArtifactDraft.objects.exists()
