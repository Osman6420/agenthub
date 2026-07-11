"""Eval runner: execute a candidate release against its pinned eval suite (Sprint 6).

The suite is resolved from the release manifest (role ``eval_suite``), so an eval is
always bound to an immutable release and its exact suite version. Each case is run
through the governed runtime with ``require_active=False`` (candidate isolation); the
active release pointer is never touched. Reports are redacted; completion is audited.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.catalog.models import ScenarioType
from apps.evaluations.assertions import evaluate_assertion
from apps.evaluations.models import EvalCaseResult, EvalRun, EvalStatus
from apps.orchestration.providers import ModelProvider, ModelProviderError
from apps.orchestration.runtime import RetrievalError, RuntimeReleaseError, run_rag
from apps.releases.models import ScenarioRelease
from apps.releases.services import get_artifact_body_for_role, get_manifest_role
from apps.retrieval.providers import RetrievalProvider
from apps.workflows.runtime import WorkflowRuntimeError, run_workflow_candidate


class EvalError(RuntimeError):
    """Raised when an eval cannot start (e.g. no suite pinned in the manifest)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _finalize(run: EvalRun, status: str, passed_cases: int, *, error_code: str = "") -> EvalRun:
    run.status = status
    run.passed_cases = passed_cases
    run.error_code = error_code
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "passed_cases", "error_code", "finished_at", "updated_at"])
    record_event(
        actor_type="system",
        actor_id="eval-runner",
        action="eval.completed",
        outcome="success" if status == EvalStatus.PASSED else "failure",
        organization_id=run.organization_id,
        resource_type="eval_run",
        resource_id=str(run.pk),
        reason=error_code or str(status),
        after={
            "release_id": run.release_id,
            "status": str(status),
            "total_cases": run.total_cases,
            "passed_cases": passed_cases,
        },
    )
    return run


def run_eval(
    *,
    release: ScenarioRelease,
    created_by: str,
    model_provider: ModelProvider | None = None,
    retrieval_provider: RetrievalProvider | None = None,
) -> EvalRun:
    """Run the release's pinned eval suite and persist a redacted, audited report."""
    entry = get_manifest_role(release, "eval_suite")
    if entry is None:
        raise EvalError("EVAL_SUITE_NOT_PINNED")
    suite_body = get_artifact_body_for_role(release, "eval_suite")
    if suite_body is None:
        raise EvalError("EVAL_SUITE_UNRESOLVED")
    cases = suite_body.get("cases", []) if isinstance(suite_body, dict) else []

    run = EvalRun(
        organization_id=release.scenario.project.organization_id,
        release=release,
        suite_ref=str(entry.get("ref", "")),
        suite_checksum=str(entry.get("checksum", "")),
        created_by=created_by,
        total_cases=len(cases),
    )
    run.full_clean()
    run.save()

    passed_cases = 0
    try:
        with transaction.atomic():
            for case in cases:
                if release.scenario.type == ScenarioType.WORKFLOW:
                    result = run_workflow_candidate(
                        release=release,
                        input_payload=dict(case.get("input", {})),
                    )
                else:
                    result = run_rag(
                        execution_context={},
                        validated_input=dict(case.get("input", {})),
                        release=release,
                        require_active=False,
                        model_provider=model_provider,
                        retrieval_provider=retrieval_provider,
                    )
                outcomes: list[dict[str, object]] = []
                case_passed = True
                for assertion in case.get("assertions", []):
                    ok, reason = evaluate_assertion(assertion, result)
                    outcomes.append(
                        {"type": assertion["type"], "passed": ok, "reason_code": reason}
                    )
                    case_passed = case_passed and ok
                EvalCaseResult.objects.create(
                    run=run,
                    case_id=str(case.get("id", "")),
                    passed=case_passed,
                    fallback_used=result.fallback_used,
                    assertions=outcomes,
                )
                if case_passed:
                    passed_cases += 1
    except (RuntimeReleaseError, RetrievalError, ModelProviderError, WorkflowRuntimeError) as exc:
        return _finalize(run, EvalStatus.ERROR, 0, error_code=type(exc).__name__)
    except Exception:  # defensive: never leak an unclassified runtime error
        return _finalize(run, EvalStatus.ERROR, 0, error_code="INTERNAL_ERROR")

    status = EvalStatus.PASSED if passed_cases == len(cases) else EvalStatus.FAILED
    return _finalize(run, status, passed_cases)
