"""Eval runner: candidate isolation, pass/fail/error, and report redaction."""

from __future__ import annotations

import pytest

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario, ScenarioType
from apps.evaluations.models import EvalCaseResult, EvalStatus
from apps.evaluations.services import EvalError, run_eval
from apps.releases.compiler import ArtifactRef, compile_release
from apps.releases.models import ReleaseStatus, ScenarioRelease
from apps.retrieval.providers import StaticRetrievalProvider
from apps.retrieval.types import RetrievedChunk
from apps.tenancy.models import Organization

GROUNDED_CHUNK = RetrievedChunk(
    text="Iade suresi urun tesliminden itibaren 14 gundur.",
    source_id="mcm",
    source_uri="https://kurum.example/iade",
    title="Iade Politikasi",
    score=0.9,
)


def _suite(assertions: list[dict]) -> dict:
    return {"cases": [{"id": "c1", "input": {"query": "iade"}, "assertions": assertions}]}


def _release_with_suite(suite_body: dict) -> ScenarioRelease:
    org = Organization.objects.create(slug="mcm", name="MCM")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(
        project=project, slug="info", name="Info", type=ScenarioType.RAG
    )
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.EVAL_SUITE,
        logical_id="info_suite",
        body=suite_body,
        created_by="alice",
    )
    return compile_release(
        scenario=scenario,
        refs=[ArtifactRef("eval_suite", ArtifactType.EVAL_SUITE, "info_suite", 1)],
        runtime_version="rt:3.0.0",
        created_by="alice",
    )


class _FailingRetrieval:
    def retrieve(self, **kwargs: object) -> list[RetrievedChunk]:
        raise RuntimeError("provider down")


@pytest.mark.django_db
def test_passing_eval_records_passed_run_without_touching_active_pointer() -> None:
    release = _release_with_suite(
        _suite(
            [
                {"type": "answer_contains", "value": "14"},
                {"type": "grounded"},
                {"type": "citations_present"},
                {"type": "min_sources", "count": 1},
            ]
        )
    )

    run = run_eval(
        release=release,
        created_by="alice",
        retrieval_provider=StaticRetrievalProvider([GROUNDED_CHUNK]),
    )

    assert run.status == EvalStatus.PASSED
    assert run.total_cases == 1 and run.passed_cases == 1
    # Candidate evaluation must never activate the release.
    release.refresh_from_db()
    assert release.status == ReleaseStatus.CANDIDATE
    assert ScenarioRelease.objects.filter(status=ReleaseStatus.ACTIVE).count() == 0


@pytest.mark.django_db
def test_failing_assertion_marks_run_failed() -> None:
    release = _release_with_suite(
        _suite([{"type": "answer_contains", "value": "kesinlikle-yok-boyle-bir-metin"}])
    )

    run = run_eval(
        release=release,
        created_by="alice",
        retrieval_provider=StaticRetrievalProvider([GROUNDED_CHUNK]),
    )

    assert run.status == EvalStatus.FAILED
    assert run.passed_cases == 0
    result = EvalCaseResult.objects.get(run=run, case_id="c1")
    assert result.passed is False
    assert result.assertions[0]["reason_code"] == "substring_absent"


@pytest.mark.django_db
def test_provider_failure_marks_run_error() -> None:
    release = _release_with_suite(_suite([{"type": "grounded"}]))

    run = run_eval(release=release, created_by="alice", retrieval_provider=_FailingRetrieval())

    assert run.status == EvalStatus.ERROR
    assert run.error_code == "RetrievalError"
    # Partial case rows rolled back on error.
    assert EvalCaseResult.objects.filter(run=run).count() == 0


@pytest.mark.django_db
def test_report_is_redacted_to_reason_codes_only() -> None:
    release = _release_with_suite(_suite([{"type": "answer_contains", "value": "14"}]))

    run = run_eval(
        release=release,
        created_by="alice",
        retrieval_provider=StaticRetrievalProvider([GROUNDED_CHUNK]),
    )

    result = EvalCaseResult.objects.get(run=run)
    # Only stable, content-free fields — never the answer or the matched value.
    assert set(result.assertions[0]) == {"type", "passed", "reason_code"}
    serialized = str(result.assertions)
    assert "Iade suresi" not in serialized and "14 gundur" not in serialized


@pytest.mark.django_db
def test_run_without_pinned_suite_raises() -> None:
    org = Organization.objects.create(slug="acme", name="Acme")
    project = AIProject.objects.create(organization=org, slug="p", name="P")
    scenario = Scenario.objects.create(project=project, slug="s", name="S", type=ScenarioType.RAG)
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.MODEL_PROFILE,
        logical_id="chat",
        body={"model": "stub"},
        created_by="alice",
    )
    release = compile_release(
        scenario=scenario,
        refs=[ArtifactRef("model_profile", ArtifactType.MODEL_PROFILE, "chat", 1)],
        runtime_version="rt:3.0.0",
        created_by="alice",
    )
    with pytest.raises(EvalError, match="EVAL_SUITE_NOT_PINNED"):
        run_eval(release=release, created_by="alice")
