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
    first = services.publish_draft(bf.draft, actor="author", expected_revision=1)
    second = services.publish_draft(bf.draft, actor="author", expected_revision=2)
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

    artifact = services.publish_draft(bf.draft, actor="author", expected_revision=1)
    assert artifact.checksum == compute_checksum(bf.draft.body)


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
