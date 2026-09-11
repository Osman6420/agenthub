"""One release evaluation resumes durable cases without replaying completed work."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from django.db import close_old_connections, connection

from apps.evaluations import services
from apps.evaluations.models import EvalCaseResult, EvalRun, EvalStatus
from apps.evaluations.tests.test_evaluations import _release_with_suite
from apps.workflows.models import Run

pytestmark = pytest.mark.django_db(transaction=True)


def candidate():
    return _release_with_suite(
        {
            "cases": [
                {
                    "id": name,
                    "input": {"query": name},
                    "assertions": [{"type": "answer_contains", "value": "14"}],
                }
                for name in ["first", "second"]
            ]
        }
    )


def test_resume_after_process_loss_keeps_exact_completed_cases(monkeypatch):
    release = candidate()
    evaluation, _ = services._admit_eval(release=release, created_by="operator")
    execute = services._execute_case
    calls = []

    def interrupted(**kwargs):
        calls.append(kwargs["ordinal"])
        if kwargs["ordinal"] == 1:
            raise SystemExit("process lost")
        return execute(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(services, "_execute_case", interrupted)
        with pytest.raises(SystemExit, match="process lost"):
            services.resume_eval(eval_run_id=evaluation.pk, organization_id=release.organization_id)
    evaluation.refresh_from_db()
    assert evaluation.status == EvalStatus.PENDING
    assert list(evaluation.case_results.values_list("case_id", flat=True)) == ["first"]
    assert Run.objects.count() == 1
    calls.clear()

    def finish(**kwargs):
        calls.append(kwargs["ordinal"])
        return execute(**kwargs)

    monkeypatch.setattr(services, "_execute_case", finish)
    result = services.resume_eval(
        eval_run_id=evaluation.pk, organization_id=release.organization_id
    )
    assert result.pk == evaluation.pk and result.status == EvalStatus.PASSED
    assert result.passed_cases == result.total_cases == 2
    assert calls == [1] and Run.objects.count() == 2
    assert EvalRun.objects.count() == 1 and EvalCaseResult.objects.count() == 2
    services.resume_eval(eval_run_id=evaluation.pk, organization_id=release.organization_id)
    assert calls == [1] and Run.objects.count() == 2
    release.refresh_from_db()
    assert release.status == "candidate"


def test_resume_after_run_completion_before_case_commit_does_not_repeat_runtime(monkeypatch):
    release = candidate()
    evaluation, cases = services._admit_eval(release=release, created_by="operator")
    consumer = services._evaluation_consumer(release)
    services._execute_case(
        eval_run=evaluation,
        release=release,
        consumer=consumer,
        case=cases[0],
        ordinal=0,
    )
    assert Run.objects.count() == 1 and not evaluation.case_results.exists()
    result = services.resume_eval(
        eval_run_id=evaluation.pk, organization_id=release.organization_id
    )
    assert result.status == "passed" and Run.objects.count() == 2


def test_resume_rechecks_scope_suite_and_does_not_retry_failed_evaluation(monkeypatch):
    release = candidate()
    evaluation, _ = services._admit_eval(release=release, created_by="operator")
    with pytest.raises(services.EvalError, match="EVALUATION_NOT_FOUND"):
        services.resume_eval(eval_run_id=evaluation.pk, organization_id=release.organization_id + 1)
    checksum = evaluation.suite_checksum
    EvalRun.objects.filter(pk=evaluation.pk).update(suite_checksum="0" * 64)
    with pytest.raises(services.EvalError, match="EVALUATION_SUITE_CHANGED"):
        services.resume_eval(eval_run_id=evaluation.pk, organization_id=release.organization_id)
    EvalRun.objects.filter(pk=evaluation.pk).update(suite_checksum=checksum)

    def unavailable(**kwargs):
        raise services.EvalError("PROVIDER_UNAVAILABLE")

    monkeypatch.setattr(services, "_execute_case", unavailable)
    result = services.resume_eval(
        eval_run_id=evaluation.pk, organization_id=release.organization_id
    )
    assert result.status == "error" and result.error_code == "PROVIDER_UNAVAILABLE"
    assert (
        services.resume_eval(
            eval_run_id=evaluation.pk, organization_id=release.organization_id
        ).status
        == "error"
    )
    assert EvalRun.objects.count() == 1 and not Run.objects.exists()


def test_two_callers_cannot_run_the_same_evaluation(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL session ownership")
    release = candidate()
    evaluation, _ = services._admit_eval(release=release, created_by="operator")
    entered, finish = Event(), Event()
    execute = services._execute_case

    def paused(**kwargs):
        if kwargs["ordinal"] == 0:
            entered.set()
            assert finish.wait(10)
        return execute(**kwargs)

    monkeypatch.setattr(services, "_execute_case", paused)

    def worker():
        close_old_connections()
        try:
            return services.resume_eval(
                eval_run_id=evaluation.pk, organization_id=release.organization_id
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        try:
            assert entered.wait(10)
            with pytest.raises(services.EvalError, match="EVALUATION_ALREADY_RUNNING"):
                services.resume_eval(
                    eval_run_id=evaluation.pk, organization_id=release.organization_id
                )
        finally:
            finish.set()
        assert future.result().status == "passed"
    assert Run.objects.count() == 2 and EvalCaseResult.objects.count() == 2
