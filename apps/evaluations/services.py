"""Evaluate immutable candidate releases through the canonical Run runtime."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.evaluations.assertions import evaluate_assertion
from apps.evaluations.models import EvalCaseResult, EvalRun, EvalStatus
from apps.gateway.execution_context import issue_execution_context
from apps.identity.capabilities import Capability
from apps.identity.models import Consumer, ConsumerProtocol
from apps.orchestration.rag_steps import retrieval_pointers_from_state
from apps.orchestration.runtime import RunResult
from apps.releases.models import ScenarioRelease
from apps.releases.services import get_artifact_body_for_role, get_manifest_role
from apps.tenancy.context import set_tenant_context
from apps.workflows.compiler import WorkflowCompileError
from apps.workflows.models import Run, RunStatus
from apps.workflows.services import (
    WorkflowRequestError,
    request_unified_run,
    resolve_release_workflow,
)
from apps.workflows.transitions import RunTransitionError, renew_sync_lease
from apps.workflows.unified_executor import UnifiedExecutorError, execute_sync_run

_TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.CANCELLED}
)


class EvalError(RuntimeError):
    """Raised when an eval cannot start."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@transaction.atomic
def _finalize(run: EvalRun, status: str, passed_cases: int, *, error_code: str = "") -> EvalRun:
    set_tenant_context(run.organization_id)
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


def summarize_eval_run(run: EvalRun) -> tuple[str, str]:
    """Return ``(level, message)`` describing one finished eval run.

    ``run_eval`` never raises for a runtime failure; it returns a run whose status is
    ``error``. Callers therefore have to branch on the status, and an ``error`` run is not a
    "0/N passed" result at all — no case was evaluated, so reporting a pass ratio invites
    the reader to debug their assertions instead of the failure that actually happened.
    """

    if run.status == EvalStatus.ERROR:
        reason = run.error_code or "EVALUATION_RUN_FAILED"
        return "error", f"Eval çalıştırılamadı ({reason}). Hiçbir test sorusu değerlendirilemedi."
    ratio = f"{run.passed_cases}/{run.total_cases}"
    if run.status == EvalStatus.PASSED:
        return "success", f"Eval geçti: {ratio} test sorusu başarılı."
    return "warning", f"Eval başarısız: {ratio} test sorusu geçti."


@transaction.atomic
def evaluation_consumer_for_organization(organization_id: int) -> Consumer:
    """The org-shared synthetic consumer that backs "Sor" and eval retrieval.

    Exposed (not prefixed) so `apps.documents.access_services` can grant it document-set
    retrieval access at bind time (BUG-015) without duplicating this lookup.
    """
    set_tenant_context(organization_id)
    consumer, _ = Consumer.objects.get_or_create(
        organization_id=organization_id,
        subject="system:evaluation",
        defaults={"name": "Evaluation runner", "protocol": ConsumerProtocol.REST},
    )
    if not consumer.is_active:
        raise EvalError("EVALUATION_CONSUMER_DISABLED")
    return consumer


def _evaluation_consumer(release: ScenarioRelease) -> Consumer:
    return evaluation_consumer_for_organization(release.organization_id)


@transaction.atomic
def _result_from_run(run: Run) -> RunResult:
    set_tenant_context(run.organization_id)
    run.refresh_from_db()
    output = run.redacted_state.get("output")
    safe_output = output if isinstance(output, dict) else {}
    executed_nodes = list(
        run.events.exclude(node_id="").order_by("sequence").values_list("node_id", flat=True)
    )
    agent = safe_output.get("agent")
    agent_meta = agent if isinstance(agent, dict) else {}
    return RunResult(
        status=str(run.status),
        output=safe_output,
        usage={
            "input_tokens": run.input_token_count,
            "output_tokens": run.output_token_count,
        },
        fallback_used=bool(safe_output.get("fallback_used", False)),
        metadata={
            "workload_type": "agent" if agent_meta else "workflow",
            "executed_nodes": executed_nodes,
            "tools_called": list(agent_meta.get("tools_called", [])),
            "decisions": list(agent_meta.get("decisions", [])),
            "steps": run.step_count,
            "escalation": agent_meta.get("escalation"),
            # Numeric-only chunk provenance, so an operator surface can show *what the run
            # retrieved* next to the answer it produced. No chunk text travels here.
            "retrieval": retrieval_pointers_from_state(run.redacted_state),
        },
    )


def _execute_case(
    *,
    eval_run: EvalRun,
    release: ScenarioRelease,
    consumer: Consumer,
    case: dict[str, Any],
    ordinal: int,
) -> RunResult:
    return execute_release_input(
        release=release,
        input_payload=dict(case.get("input", {})),
        request_key=f"eval:{eval_run.pk}:{ordinal}",
        prepared_evaluation=eval_run if eval_run.prepared_source_job_id else None,
    )


def execute_release_input(
    *,
    release: ScenarioRelease,
    input_payload: dict[str, Any],
    request_key: str,
    prepared_evaluation: EvalRun | None = None,
) -> RunResult:
    """Execute one bounded evaluation input against an exact release."""

    run, lease_token = _admit_evaluation_input(
        release=release,
        input_payload=input_payload,
        request_key=request_key,
        prepared_evaluation=prepared_evaluation,
    )
    if lease_token is not None:
        execute_sync_run(
            organization_id=run.organization_id, run_id=run.id, lease_token=lease_token
        )
    result = _result_from_run(run)
    if result.status != RunStatus.COMPLETED:
        raise EvalError(run.error_code or run.reason_code or "EVALUATION_RUN_FAILED")
    return result


@transaction.atomic
def _admit_evaluation_input(
    *,
    release: ScenarioRelease,
    input_payload: dict[str, Any],
    request_key: str,
    prepared_evaluation: EvalRun | None = None,
) -> tuple[Run, uuid.UUID | None]:
    """Commit admission and lease before executing any evaluation node."""

    set_tenant_context(release.organization_id)
    consumer = _evaluation_consumer(release)
    workflow_version = resolve_release_workflow(release)
    scenario = release.scenario
    execution_context = issue_execution_context(
        organization_id=consumer.organization_id,
        project_id=scenario.project_id,
        scenario_id=scenario.id,
        scenario_alias=scenario.slug,
        consumer_id=consumer.id,
        capabilities=[Capability.WORKFLOW_RUN],
        release_id=release.id,
        request_id=request_key,
    )
    run, created = request_unified_run(
        release=release,
        consumer=consumer,
        workflow_version=workflow_version,
        execution_context=execution_context,
        input_payload=input_payload,
        idempotency_key=request_key,
        execution_mode="sync",
        prepared_evaluation=prepared_evaluation,
    )
    if not created and run.status in _TERMINAL_RUN_STATUSES:
        # BUG-011: the exact same `request_key` (e.g. the identical question re-asked) replays
        # the already-terminal run's own result instead of renewing a lease and re-executing it.
        # `renew_sync_lease` rejects a COMPLETED run with `RunTransitionError`, which previously
        # reached the caller as a bare 500 with a full debug traceback.
        if run.status != RunStatus.COMPLETED:
            raise EvalError(run.error_code or run.reason_code or "EVALUATION_RUN_FAILED")
        return run, None
    lease_token = uuid.uuid4()
    renew_sync_lease(
        organization_id=run.organization_id,
        run_id=run.id,
        lease_token=lease_token,
        expires_at=min(run.deadline_at, timezone.now() + timedelta(seconds=30)),
    )
    return run, lease_token


@transaction.atomic
def _admit_eval(
    *,
    release: ScenarioRelease,
    created_by: str,
    prepared_source_job=None,
    prepared_actor=None,
    generation_count: int = 0,
) -> tuple[EvalRun, list[dict[str, Any]]]:
    set_tenant_context(release.organization_id)
    entry = get_manifest_role(release, "eval_suite")
    if entry is None:
        raise EvalError("EVAL_SUITE_NOT_PINNED")
    suite_body = get_artifact_body_for_role(release, "eval_suite")
    if suite_body is None:
        raise EvalError("EVAL_SUITE_UNRESOLVED")
    cases = suite_body.get("cases", []) if isinstance(suite_body, dict) else []

    eval_run = EvalRun(
        organization_id=release.organization_id,
        release=release,
        suite_ref=str(entry.get("ref", "")),
        suite_checksum=str(entry.get("checksum", "")),
        created_by=created_by,
        total_cases=len(cases),
        prepared_source_job=prepared_source_job,
        prepared_actor=prepared_actor,
        generation_count=generation_count,
    )
    eval_run.full_clean()
    eval_run.save()
    return eval_run, cases


def run_eval(*, release: ScenarioRelease, created_by: str) -> EvalRun:
    """Run the pinned suite with independently committed execution and results."""

    eval_run, _ = _admit_eval(release=release, created_by=created_by)
    return resume_eval(eval_run_id=eval_run.pk, organization_id=release.organization_id)


def resume_eval(*, eval_run_id: int, organization_id: int) -> EvalRun:
    """Continue one exact evaluation; completed evidence never starts paid work again.

    This is an internal execution seam, not an authorization API. Operator callers
    must authorize the scenario before admission/resume and again before publication.
    """
    from apps.evaluations.execution_lock import release_evaluation_lock

    with release_evaluation_lock(organization_id, eval_run_id) as acquired:
        if not acquired:
            raise EvalError("EVALUATION_ALREADY_RUNNING")
        with transaction.atomic():
            set_tenant_context(organization_id)
            eval_run = (
                EvalRun.objects.select_related("release")
                .filter(
                    pk=eval_run_id,
                    organization_id=organization_id,
                    release__organization_id=organization_id,
                )
                .first()
            )
            if eval_run is None:
                raise EvalError("EVALUATION_NOT_FOUND")
            release = eval_run.release
            entry = get_manifest_role(release, "eval_suite")
            suite_body = get_artifact_body_for_role(release, "eval_suite")
            cases = suite_body.get("cases", []) if isinstance(suite_body, dict) else []
            if (
                entry is None
                or suite_body is None
                or eval_run.suite_checksum != entry.get("checksum")
                or eval_run.suite_ref != entry.get("ref")
                or eval_run.total_cases != len(cases)
            ):
                raise EvalError("EVALUATION_SUITE_CHANGED")
            if eval_run.status != EvalStatus.PENDING:
                return eval_run
            evidence = dict(eval_run.case_results.values_list("case_id", "passed"))
            if set(evidence) - {str(case.get("id", "")) for case in cases}:
                raise EvalError("EVALUATION_EVIDENCE_INVALID")
        return _continue_pending_eval(eval_run, cases, evidence)


def _continue_pending_eval(
    eval_run: EvalRun, cases: list[dict[str, Any]], evidence: dict[str, bool]
) -> EvalRun:
    release = eval_run.release

    passed_cases = sum(evidence.values())
    try:
        consumer = _evaluation_consumer(release)
        for ordinal, case in enumerate(cases):
            if str(case.get("id", "")) in evidence:
                continue
            result = _execute_case(
                eval_run=eval_run,
                release=release,
                consumer=consumer,
                case=case,
                ordinal=ordinal,
            )
            outcomes: list[dict[str, object]] = []
            case_passed = True
            for assertion in case.get("assertions", []):
                ok, reason = evaluate_assertion(assertion, result)
                outcomes.append({"type": assertion["type"], "passed": ok, "reason_code": reason})
                case_passed = case_passed and ok
            with transaction.atomic():
                set_tenant_context(release.organization_id)
                EvalCaseResult.objects.create(
                    run=eval_run,
                    case_id=str(case.get("id", "")),
                    passed=case_passed,
                    fallback_used=result.fallback_used,
                    assertions=outcomes,
                )
            if case_passed:
                passed_cases += 1
    except (
        EvalError,
        WorkflowCompileError,
        WorkflowRequestError,
        RunTransitionError,
        UnifiedExecutorError,
    ) as exc:
        code = exc.code if isinstance(exc, EvalError) else type(exc).__name__
        return _finalize(eval_run, EvalStatus.ERROR, passed_cases, error_code=code)
    except Exception:
        return _finalize(eval_run, EvalStatus.ERROR, passed_cases, error_code="INTERNAL_ERROR")

    status = EvalStatus.PASSED if passed_cases == len(cases) else EvalStatus.FAILED
    return _finalize(eval_run, status, passed_cases)
