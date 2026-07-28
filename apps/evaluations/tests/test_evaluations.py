"""Evaluation uses the same canonical Run aggregate as public execution."""

from __future__ import annotations

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.evaluations.models import EvalCaseResult, EvalStatus
from apps.evaluations.services import EvalError, run_eval
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.tenancy.models import Organization
from apps.workflows.models import Run, RunEvent, RunStatus
from apps.workflows.unified_executor import UnifiedExecutorError


def _suite(assertions: list[dict]) -> dict:
    return {"cases": [{"id": "c1", "input": {"query": "iade"}, "assertions": assertions}]}


def _workflow(answer: str = "14 gun") -> dict:
    return {
        "api_version": "agenthub/v1",
        "kind": "Workflow",
        "metadata": {"id": "evaluation.v1"},
        "spec": {
            "input_node": "request",
            "nodes": [
                {"id": "request", "type": "input"},
                {"id": "answer", "type": "format_output", "config": {"template_ref": answer}},
                {"id": "done", "type": "end"},
            ],
            "edges": [
                {"from": "request", "to": "answer"},
                {"from": "answer", "to": "done"},
            ],
        },
    }


def _release_with_suite(suite_body: dict, *, answer: str = "14 gun") -> ScenarioRelease:
    org = Organization.objects.create(slug="mcm", name="MCM")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(project=project, slug="info", name="Info")
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.EVAL_SUITE,
        logical_id="info_suite",
        body=suite_body,
        created_by="alice",
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="info_workflow",
        body=_workflow(answer),
        created_by="alice",
    )
    return compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef("eval_suite", ArtifactType.EVAL_SUITE, "info_suite", 1),
            ArtifactRef(
                "workflow_definition",
                ArtifactType.WORKFLOW_DEFINITION,
                "info_workflow",
                1,
            ),
        ],
        runtime_version="rt:3.0.0",
        created_by="alice",
    )


@pytest.mark.django_db
def test_passing_eval_leaves_completed_run_and_ordered_events() -> None:
    release = _release_with_suite(
        _suite(
            [
                {"type": "answer_contains", "value": "14"},
                {"type": "workflow_completed"},
            ]
        )
    )

    evaluation = run_eval(release=release, created_by="alice")

    assert evaluation.status == EvalStatus.PASSED
    assert evaluation.total_cases == evaluation.passed_cases == 1
    execution = Run.objects.get(release=release)
    assert execution.status == RunStatus.COMPLETED
    assert list(execution.events.values_list("sequence", flat=True)) == list(
        range(1, RunEvent.objects.filter(run=execution).count() + 1)
    )
    release.refresh_from_db()
    assert release.status == ReleaseStatus.CANDIDATE
    assert ScenarioRelease.objects.filter(status=ReleaseStatus.ACTIVE).count() == 0


@pytest.mark.django_db
def test_failing_assertion_marks_eval_failed_and_report_is_redacted() -> None:
    release = _release_with_suite(_suite([{"type": "answer_contains", "value": "kesinlikle-yok"}]))

    evaluation = run_eval(release=release, created_by="alice")

    assert evaluation.status == EvalStatus.FAILED
    result = EvalCaseResult.objects.get(run=evaluation, case_id="c1")
    assert result.passed is False
    assert result.assertions == [
        {
            "type": "answer_contains",
            "passed": False,
            "reason_code": "substring_absent",
        }
    ]
    assert "14 gun" not in str(result.assertions)


@pytest.mark.django_db
def test_runtime_failure_marks_eval_error_but_preserves_run_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _release_with_suite(_suite([{"type": "workflow_completed"}]))

    def _fail(**_kwargs: object) -> None:
        raise UnifiedExecutorError("RUN_EXECUTOR_TEST_FAILURE")

    monkeypatch.setattr("apps.evaluations.services.execute_sync_run", _fail)
    evaluation = run_eval(release=release, created_by="alice")

    assert evaluation.status == EvalStatus.ERROR
    assert evaluation.error_code == "UnifiedExecutorError"
    assert Run.objects.filter(release=release).exists()


@pytest.mark.django_db
def test_run_without_pinned_suite_raises() -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    project = AIProject.objects.create(organization=org, slug="p", name="P")
    scenario = Scenario.objects.create(project=project, slug="s", name="S")
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.WORKFLOW_DEFINITION,
        logical_id="workflow",
        body=_workflow(),
        created_by="alice",
    )
    release = compile_release(
        scenario=scenario,
        refs=[
            ArtifactRef(
                "workflow_definition",
                ArtifactType.WORKFLOW_DEFINITION,
                "workflow",
                1,
            )
        ],
        runtime_version="rt:3.0.0",
        created_by="alice",
    )
    with pytest.raises(EvalError, match="EVAL_SUITE_NOT_PINNED"):
        run_eval(release=release, created_by="alice")
