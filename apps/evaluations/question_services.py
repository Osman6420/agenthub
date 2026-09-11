"""Phase 2.8 Part 6 question-set and exact-provenance evaluation services."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import jsonschema
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.audit.services import record_event
from apps.documents.models import DocumentSetVersion, DocumentSetVersionStatus
from apps.evaluations.execution_lock import question_evaluation_lock
from apps.evaluations.models import (
    QuestionCase,
    QuestionEvaluationEvidence,
    QuestionEvaluationEvidenceStatus,
    QuestionEvaluationKind,
    QuestionEvaluationRun,
    QuestionEvaluationStatus,
    QuestionSet,
    QuestionSetStatus,
    QuestionSetVersion,
)
from apps.evaluations.services import EvalError, execute_release_input
from apps.identity.authorization import Capability, authorize
from apps.ingestion.models import IndexStatus, IndexVersion
from apps.ingestion.vector_store import VectorStoreError, exact_chunk_text
from apps.observability.metrics import (
    QUESTION_EVAL_CASES,
    QUESTION_EVAL_DURATION,
    QUESTION_EVAL_RUNS,
)
from apps.orchestration.providers import ModelProviderError, get_model_provider
from apps.releases.models import ScenarioRelease
from apps.retrieval.providers import get_retrieval_provider
from apps.retrieval.types import RetrievedChunk
from apps.tenancy.context import operator_transaction, set_tenant_context

MAX_CASES = 200
MAX_QUESTION_CHARS = 4000
MAX_ASSERTIONS = 20
MAX_ANCHORS = 50
MAX_ANSWER_CHARS = 12_000
MAX_EVIDENCE_CHUNKS = 50
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CHECKSUM = re.compile(r"^[0-9a-f]{64}$")
_ASSERTION_TYPES = {"exact", "normalized_contains", "citation_source", "output_schema"}


class QuestionEvaluationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OneOffResult:
    answer: str
    chunks: list[RetrievedChunk]
    error_code: str = ""


def can_manage_question_sets(user: Any, organization: Any) -> bool:
    """Organization-owned evaluation assets require organization administration."""
    return authorize(
        user=user,
        capability=Capability.ORGANIZATION_MANAGE,
        organization=organization,
    ).allowed


def can_read_question_sets(user: Any, organization: Any) -> bool:
    return can_manage_question_sets(user, organization)


def _require_question_set_author(user: Any, organization: Any) -> None:
    if not can_manage_question_sets(user, organization):
        raise QuestionEvaluationError("QUESTION_SET_AUTHORIZATION_DENIED")


def _bounded_string(value: Any, *, maximum: int, code: str) -> str:
    if not isinstance(value, str):
        raise QuestionEvaluationError(code)
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise QuestionEvaluationError(code)
    return normalized


def _normalize_assertion(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"type", "value", "schema"}:
        raise QuestionEvaluationError("QUESTION_ASSERTION_INVALID")
    kind = value.get("type")
    if kind not in _ASSERTION_TYPES:
        raise QuestionEvaluationError("QUESTION_ASSERTION_INVALID")
    if kind == "output_schema":
        schema = value.get("schema")
        if not isinstance(schema, dict):
            raise QuestionEvaluationError("QUESTION_ASSERTION_INVALID")
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise QuestionEvaluationError("QUESTION_ASSERTION_INVALID") from exc
        return {"type": kind, "schema": schema}
    expected = _bounded_string(value.get("value"), maximum=4000, code="QUESTION_ASSERTION_INVALID")
    return {"type": kind, "value": expected}


def _normalize_anchor(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        "document_version_id",
        "ordinal",
        "passage_checksum",
    }:
        raise QuestionEvaluationError("QUESTION_ANCHOR_INVALID")
    document_version_id = value.get("document_version_id")
    if (
        isinstance(document_version_id, bool)
        or not isinstance(document_version_id, int)
        or document_version_id <= 0
    ):
        raise QuestionEvaluationError("QUESTION_ANCHOR_INVALID")
    anchor: dict[str, Any] = {"document_version_id": document_version_id}
    ordinal = value.get("ordinal")
    if ordinal is not None:
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            raise QuestionEvaluationError("QUESTION_ANCHOR_INVALID")
        anchor["ordinal"] = ordinal
    checksum = value.get("passage_checksum")
    if checksum is not None:
        if not isinstance(checksum, str) or not _CHECKSUM.fullmatch(checksum):
            raise QuestionEvaluationError("QUESTION_ANCHOR_INVALID")
        anchor["passage_checksum"] = checksum
    return anchor


def normalize_cases(raw_cases: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_cases, list) or not raw_cases or len(raw_cases) > MAX_CASES:
        raise QuestionEvaluationError("QUESTION_CASE_COUNT_INVALID")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict) or set(raw) - {
            "id",
            "question",
            "input",
            "assertions",
            "expected_answer",
            "expected_anchors",
            "judge",
        }:
            raise QuestionEvaluationError("QUESTION_CASE_INVALID")
        case_id = raw.get("id")
        if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id) or case_id in seen:
            raise QuestionEvaluationError("QUESTION_CASE_ID_INVALID")
        seen.add(case_id)
        question = _bounded_string(
            raw.get("question"), maximum=MAX_QUESTION_CHARS, code="QUESTION_TEXT_INVALID"
        )
        input_payload = raw.get("input", {})
        if not isinstance(input_payload, dict) or len(json.dumps(input_payload)) > 20_000:
            raise QuestionEvaluationError("QUESTION_INPUT_INVALID")
        raw_assertions = raw.get("assertions", [])
        if not isinstance(raw_assertions, list) or len(raw_assertions) > MAX_ASSERTIONS:
            raise QuestionEvaluationError("QUESTION_ASSERTION_INVALID")
        assertions = [_normalize_assertion(item) for item in raw_assertions]
        raw_expected = raw.get("expected_answer", "")
        if not isinstance(raw_expected, str) or len(raw_expected) > MAX_QUESTION_CHARS:
            raise QuestionEvaluationError("QUESTION_EXPECTED_ANSWER_INVALID")
        expected_answer = raw_expected.strip()
        raw_anchors = raw.get("expected_anchors", [])
        if not isinstance(raw_anchors, list) or len(raw_anchors) > MAX_ANCHORS:
            raise QuestionEvaluationError("QUESTION_ANCHOR_INVALID")
        anchors = [_normalize_anchor(item) for item in raw_anchors]
        judge = raw.get("judge", {})
        if not isinstance(judge, dict) or set(judge) - {"enabled", "required"}:
            raise QuestionEvaluationError("QUESTION_JUDGE_POLICY_INVALID")
        judge_policy = {
            "enabled": bool(judge.get("enabled", False)),
            "required": bool(judge.get("required", False)),
        }
        if judge_policy["required"] and not judge_policy["enabled"]:
            raise QuestionEvaluationError("QUESTION_JUDGE_POLICY_INVALID")
        normalized.append(
            {
                "id": case_id,
                "question": question,
                "input": input_payload,
                "assertions": assertions,
                "expected_answer": expected_answer,
                "expected_anchors": anchors,
                "judge": judge_policy,
            }
        )
    return normalized


def _cases_checksum(cases: list[dict[str, Any]]) -> str:
    encoded = json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


@transaction.atomic
def create_question_set(
    *,
    organization: Any,
    user: Any,
    name: str,
    description: str,
    cases: Any,
    request_id: str = "",
) -> QuestionSet:
    _require_question_set_author(user, organization)
    normalized_name = _bounded_string(name, maximum=200, code="QUESTION_SET_NAME_INVALID")
    normalized_description = description.strip()
    if len(normalized_description) > 1000:
        raise QuestionEvaluationError("QUESTION_SET_DESCRIPTION_INVALID")
    normalized_cases = normalize_cases(cases)
    question_set = QuestionSet(
        organization=organization,
        name=normalized_name,
        description=normalized_description,
        draft_cases=normalized_cases,
        created_by=user.get_username(),
        updated_by=user.get_username(),
    )
    question_set.full_clean()
    try:
        question_set.save()
    except IntegrityError as exc:
        raise QuestionEvaluationError("QUESTION_SET_NAME_CONFLICT") from exc
    record_event(
        actor_type="user",
        actor_id=str(user.pk),
        action="evaluation.question_set.created",
        outcome="success",
        organization_id=organization.pk,
        resource_type="question_set",
        resource_id=str(question_set.public_id),
        reason="created",
        request_id=request_id,
        after={"draft_revision": 1, "case_count": len(normalized_cases)},
    )
    return question_set


@transaction.atomic
def update_question_set_draft(
    *,
    question_set: QuestionSet,
    user: Any,
    expected_revision: int,
    name: str,
    description: str,
    cases: Any,
    request_id: str = "",
) -> QuestionSet:
    _require_question_set_author(user, question_set.organization)
    locked = QuestionSet.objects.select_for_update().get(pk=question_set.pk)
    if locked.status != QuestionSetStatus.ACTIVE:
        raise QuestionEvaluationError("QUESTION_SET_ARCHIVED")
    if locked.draft_revision != expected_revision:
        raise QuestionEvaluationError("QUESTION_SET_REVISION_CONFLICT")
    locked.name = _bounded_string(name, maximum=200, code="QUESTION_SET_NAME_INVALID")
    locked.description = description.strip()
    if len(locked.description) > 1000:
        raise QuestionEvaluationError("QUESTION_SET_DESCRIPTION_INVALID")
    locked.draft_cases = normalize_cases(cases)
    locked.draft_revision += 1
    locked.updated_by = user.get_username()
    locked.full_clean()
    try:
        locked.save()
    except IntegrityError as exc:
        raise QuestionEvaluationError("QUESTION_SET_NAME_CONFLICT") from exc
    record_event(
        actor_type="user",
        actor_id=str(user.pk),
        action="evaluation.question_set.draft_updated",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="question_set",
        resource_id=str(locked.public_id),
        reason="updated",
        request_id=request_id,
        after={
            "draft_revision": locked.draft_revision,
            "case_count": len(locked.draft_cases),
        },
    )
    return locked


@transaction.atomic
def publish_question_set(
    *,
    question_set: QuestionSet,
    user: Any,
    expected_revision: int,
    request_id: str = "",
) -> QuestionSetVersion:
    """Publish an organization-wide question set. Requires organization administration."""

    _require_question_set_author(user, question_set.organization)
    return publish_question_set_version(
        question_set=question_set,
        published_by=user.get_username(),
        actor_id=str(user.pk),
        expected_revision=expected_revision,
        request_id=request_id,
    )


def publish_question_set_version(
    *,
    question_set: QuestionSet,
    published_by: str,
    actor_id: str,
    expected_revision: int,
    request_id: str = "",
) -> QuestionSetVersion:
    """Freeze the draft into an immutable version.

    Authorization is the caller's: an organization-wide set is guarded by
    :func:`publish_question_set`, while a scenario-owned set is guarded by scenario-editor
    authority in the console. The version-and-case writing itself lives here once so the two
    surfaces cannot drift.
    """

    locked = QuestionSet.objects.select_for_update().get(pk=question_set.pk)
    if locked.status != QuestionSetStatus.ACTIVE:
        raise QuestionEvaluationError("QUESTION_SET_ARCHIVED")
    if locked.draft_revision != expected_revision:
        raise QuestionEvaluationError("QUESTION_SET_REVISION_CONFLICT")
    cases = normalize_cases(locked.draft_cases)
    checksum = _cases_checksum(cases)
    existing = locked.versions.filter(checksum=checksum).first()
    if existing is not None:
        return existing
    next_version = (locked.versions.aggregate(value=Max("version"))["value"] or 0) + 1
    version = QuestionSetVersion(
        organization=locked.organization,
        question_set=locked,
        version=next_version,
        checksum=checksum,
        case_count=len(cases),
        published_by=published_by,
        published_at=timezone.now(),
    )
    version.full_clean()
    version.save()
    QuestionCase.objects.bulk_create(
        [
            QuestionCase(
                organization=locked.organization,
                question_set_version=version,
                case_id=case["id"],
                ordinal=ordinal,
                question=case["question"],
                input_payload=case["input"],
                assertions=case["assertions"],
                expected_answer=case.get("expected_answer", ""),
                expected_anchors=case["expected_anchors"],
                judge_policy=case["judge"],
            )
            for ordinal, case in enumerate(cases)
        ]
    )
    record_event(
        actor_type="user",
        actor_id=actor_id,
        action="evaluation.question_set.published",
        outcome="success",
        organization_id=locked.organization_id,
        resource_type="question_set_version",
        resource_id=str(version.public_id),
        reason=checksum,
        request_id=request_id,
        after={"version": version.version, "case_count": version.case_count},
    )
    return version


def _validate_version_lineage(version: QuestionSetVersion, organization_id: int) -> None:
    if version.organization_id != organization_id:
        raise QuestionEvaluationError("QUESTION_SET_VERSION_NOT_FOUND")


@transaction.atomic
def create_retrieval_evaluation(
    *,
    user: Any,
    question_set_version: QuestionSetVersion,
    document_set_version: DocumentSetVersion,
    index_version: IndexVersion,
    retrieval_profile: ArtifactVersion,
    idempotency_key: str,
    request_id: str = "",
) -> tuple[QuestionEvaluationRun, bool]:
    organization = document_set_version.organization
    _validate_version_lineage(question_set_version, organization.pk)
    decision = authorize(
        user=user,
        capability=Capability.DOCUMENT_SET_OPERATIONS_MANAGE,
        organization=organization,
        document_set=document_set_version.document_set,
    )
    if not decision.allowed:
        raise QuestionEvaluationError("RETRIEVAL_EVALUATION_AUTHORIZATION_DENIED")
    if document_set_version.status not in {
        DocumentSetVersionStatus.PROMOTABLE,
        DocumentSetVersionStatus.ACTIVE,
    }:
        raise QuestionEvaluationError("DOCUMENT_SET_VERSION_NOT_EVALUABLE")
    current_index = (
        IndexVersion.objects.select_for_update()
        .filter(
            pk=index_version.pk,
            organization_id=organization.pk,
        )
        .first()
    )
    if current_index is None:
        raise QuestionEvaluationError("INDEX_VERSION_NOT_EVALUABLE")
    index_version = current_index
    if (
        index_version.organization_id != organization.pk
        or index_version.document_set_version_id != document_set_version.pk
        or index_version.status not in {IndexStatus.PROMOTABLE, IndexStatus.ACTIVE}
        or not index_version.store_ready
    ):
        raise QuestionEvaluationError("INDEX_VERSION_NOT_EVALUABLE")
    # Tenant and type are the safety checks. The profile no longer has to be the one pinned on
    # the index: retrieval settings are applied at query time and never shaped the build, so
    # requiring a match only tied this to an ownership model the Retrieve node has taken over.
    # The exact profile ref and checksum are still recorded in the run's provenance below, so a
    # report always states what it measured with.
    if (
        retrieval_profile.organization_id != organization.pk
        or retrieval_profile.type != ArtifactType.RETRIEVAL_PROFILE
    ):
        raise QuestionEvaluationError("RETRIEVAL_PROFILE_NOT_EVALUABLE")
    key = _bounded_string(idempotency_key, maximum=128, code="EVALUATION_IDEMPOTENCY_KEY_INVALID")
    existing = QuestionEvaluationRun.objects.filter(
        organization=organization, idempotency_key=key
    ).first()
    if existing is not None:
        return existing, False
    run = QuestionEvaluationRun(
        organization=organization,
        question_set_version=question_set_version,
        kind=QuestionEvaluationKind.RETRIEVAL,
        document_set_version=document_set_version,
        index_version=index_version,
        retrieval_profile=retrieval_profile,
        idempotency_key=key,
        total_cases=question_set_version.case_count,
        created_by=user.get_username(),
        retention_until=timezone.now()
        + timedelta(days=int(getattr(settings, "EVALUATION_EVIDENCE_RETENTION_DAYS", 30))),
        provenance={
            "question_set_checksum": question_set_version.checksum,
            "document_set_version_id": document_set_version.pk,
            "index_version_id": index_version.pk,
            "retrieval_profile_ref": retrieval_profile.ref,
            "retrieval_profile_checksum": retrieval_profile.checksum,
        },
    )
    run.full_clean()
    run.save()
    _audit_run(run, action="started", actor_id=str(user.pk), request_id=request_id)
    return run, True


@transaction.atomic
def create_answer_evaluation(
    *,
    user: Any,
    question_set_version: QuestionSetVersion,
    release: ScenarioRelease,
    idempotency_key: str,
    judge_model_profile: ArtifactVersion | None = None,
    judge_prompt_contract: ArtifactVersion | None = None,
    request_id: str = "",
) -> tuple[QuestionEvaluationRun, bool]:
    organization = release.organization
    _validate_version_lineage(question_set_version, organization.pk)
    decision = authorize(
        user=user,
        capability=Capability.SCENARIO_TEST,
        organization=organization,
        project=release.scenario.project,
        scenario=release.scenario,
    )
    if not decision.allowed:
        raise QuestionEvaluationError("ANSWER_EVALUATION_AUTHORIZATION_DENIED")
    _validate_judge_profiles(
        organization_id=organization.pk,
        model_profile=judge_model_profile,
        prompt_contract=judge_prompt_contract,
    )
    key = _bounded_string(idempotency_key, maximum=128, code="EVALUATION_IDEMPOTENCY_KEY_INVALID")
    existing = QuestionEvaluationRun.objects.filter(
        organization=organization, idempotency_key=key
    ).first()
    if existing is not None:
        return existing, False
    run = QuestionEvaluationRun(
        organization=organization,
        question_set_version=question_set_version,
        kind=QuestionEvaluationKind.ANSWER,
        release=release,
        judge_model_profile=judge_model_profile,
        judge_prompt_contract=judge_prompt_contract,
        idempotency_key=key,
        total_cases=question_set_version.case_count,
        created_by=user.get_username(),
        retention_until=timezone.now()
        + timedelta(days=int(getattr(settings, "EVALUATION_EVIDENCE_RETENTION_DAYS", 30))),
        provenance={
            "question_set_checksum": question_set_version.checksum,
            "release_id": release.pk,
            "release_manifest_checksum": release.artifact_manifest_sha256,
            "judge_model_ref": judge_model_profile.ref if judge_model_profile else None,
            "judge_model_checksum": judge_model_profile.checksum if judge_model_profile else None,
            "judge_prompt_ref": judge_prompt_contract.ref if judge_prompt_contract else None,
            "judge_prompt_checksum": (
                judge_prompt_contract.checksum if judge_prompt_contract else None
            ),
        },
    )
    run.full_clean()
    run.save()
    _audit_run(run, action="started", actor_id=str(user.pk), request_id=request_id)
    return run, True


def _validate_judge_profiles(
    *,
    organization_id: int,
    model_profile: ArtifactVersion | None,
    prompt_contract: ArtifactVersion | None,
) -> None:
    if bool(model_profile) != bool(prompt_contract):
        raise QuestionEvaluationError("JUDGE_PROVENANCE_INCOMPLETE")
    if model_profile is None or prompt_contract is None:
        return
    if (
        model_profile.organization_id != organization_id
        or model_profile.type != ArtifactType.MODEL_PROFILE
        or prompt_contract.organization_id != organization_id
        or prompt_contract.type != ArtifactType.PROMPT_TEMPLATE
    ):
        raise QuestionEvaluationError("JUDGE_PROVENANCE_INVALID")
    if not getattr(settings, "EVALUATION_LLM_JUDGE_ENABLED", False):
        raise QuestionEvaluationError("JUDGE_DISABLED")


def _audit_run(
    run: QuestionEvaluationRun,
    *,
    action: str,
    actor_id: str,
    request_id: str = "",
) -> None:
    record_event(
        actor_type="system" if actor_id == "evaluation-worker" else "user",
        actor_id=actor_id,
        action=f"evaluation.question_run.{action}",
        outcome="success" if run.status != QuestionEvaluationStatus.FAILED else "failure",
        organization_id=run.organization_id,
        resource_type="question_evaluation_run",
        resource_id=str(run.public_id),
        reason=run.error_code or run.status,
        request_id=request_id,
        after={
            "kind": run.kind,
            "status": run.status,
            "total_cases": run.total_cases,
            "completed_cases": run.completed_cases,
            "passed_cases": run.passed_cases,
            "unscored_cases": run.unscored_cases,
            "error_cases": run.error_cases,
        },
    )


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _passage_checksum(value: str) -> str:
    return hashlib.sha256(_normalized_text(value).encode()).hexdigest()


def _anchor_matches(anchor: dict[str, Any], chunk: RetrievedChunk) -> bool:
    if chunk.document_version_id != anchor["document_version_id"]:
        return False
    if "ordinal" in anchor and chunk.ordinal != anchor["ordinal"]:
        return False
    if "passage_checksum" in anchor and _passage_checksum(chunk.text) != anchor["passage_checksum"]:
        return False
    return True


def score_retrieval(
    anchors: list[dict[str, Any]], chunks: list[RetrievedChunk]
) -> tuple[dict[str, float | int | None], list[dict[str, Any]]]:
    matched_anchor_indexes: set[int] = set()
    first_rank: int | None = None
    evidence: list[dict[str, Any]] = []
    for rank, chunk in enumerate(chunks[:MAX_EVIDENCE_CHUNKS], start=1):
        matched = [index for index, anchor in enumerate(anchors) if _anchor_matches(anchor, chunk)]
        matched_anchor_indexes.update(matched)
        if matched and first_rank is None:
            first_rank = rank
        evidence.append(
            {
                "rank": rank,
                "document_version_id": chunk.document_version_id,
                "document_set_version_id": chunk.document_set_version_id,
                "index_version_id": chunk.index_version_id,
                "ordinal": chunk.ordinal,
                "source_uri": chunk.source_uri,
                "title": chunk.title,
                "text_checksum": _passage_checksum(chunk.text),
                "score": chunk.score,
                "vector_rank": chunk.vector_rank,
                "vector_score": chunk.vector_score,
                "keyword_rank": chunk.keyword_rank,
                "keyword_score": chunk.keyword_score,
                "fused_score": chunk.fused_score,
                "document_routing_score": chunk.document_routing_score,
                "retrieval_stage": chunk.retrieval_stage,
                "matched": bool(matched),
            }
        )
    if not anchors:
        return {"hit": None, "recall": None, "reciprocal_rank": None, "anchor_count": 0}, evidence
    return (
        {
            "hit": 1 if matched_anchor_indexes else 0,
            "recall": len(matched_anchor_indexes) / len(anchors),
            "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
            "anchor_count": len(anchors),
        },
        evidence,
    )


def _answer_text(output: dict[str, Any]) -> str:
    answer = output.get("answer", "")
    return answer if isinstance(answer, str) else ""


def _sources(output: dict[str, Any]) -> list[Any]:
    value = output.get("sources", [])
    return value if isinstance(value, list) else []


def evaluate_answer_assertions(
    assertions: list[dict[str, Any]], output: dict[str, Any]
) -> list[dict[str, Any]]:
    answer = _answer_text(output)
    normalized_answer = _normalized_text(answer)
    outcomes: list[dict[str, Any]] = []
    for assertion in assertions:
        kind = assertion["type"]
        passed = False
        reason = "assertion_failed"
        if kind == "exact":
            passed = normalized_answer == _normalized_text(assertion["value"])
            reason = "exact_match" if passed else "exact_mismatch"
        elif kind == "normalized_contains":
            passed = _normalized_text(assertion["value"]) in normalized_answer
            reason = "contains" if passed else "substring_absent"
        elif kind == "citation_source":
            expected = assertion["value"]
            passed = any(
                source == expected
                or (
                    isinstance(source, dict)
                    and expected
                    in {
                        str(source.get("source_id", "")),
                        str(source.get("source_uri", "")),
                        str(source.get("document_version_id", "")),
                    }
                )
                for source in _sources(output)
            )
            reason = "source_present" if passed else "source_absent"
        elif kind == "output_schema":
            try:
                jsonschema.validate(output, assertion["schema"])
                passed = True
                reason = "schema_valid"
            except jsonschema.ValidationError:
                reason = "schema_invalid"
        outcome: dict[str, Any] = {"type": kind, "passed": passed, "reason_code": reason}
        # Carry the expected literal so a multi-term row names *which* term was missing
        # rather than reporting one opaque failure. It is author content, so the report
        # renders it only for a viewer who may already see questions and answers.
        if kind in {"exact", "normalized_contains", "citation_source"}:
            outcome["value"] = str(assertion.get("value", ""))
        outcomes.append(outcome)
    return outcomes


def _judge_case(
    *,
    run: QuestionEvaluationRun,
    case: QuestionCase,
    answer: str,
) -> dict[str, Any]:
    if not case.judge_policy.get("enabled"):
        return {}
    if run.judge_model_profile is None or run.judge_prompt_contract is None:
        return {"status": "unscored", "reason_code": "JUDGE_NOT_PINNED"}
    prompt = run.judge_prompt_contract.body.get("template")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20_000:
        return {"status": "unscored", "reason_code": "JUDGE_PROMPT_INVALID"}
    # The expected answer is the author's intent, not a literal to match; the pinned judge
    # prompt decides how to weigh it. Absent when the author did not supply one.
    judge_context: dict[str, str] = {"question": case.question, "answer": answer}
    if case.expected_answer:
        judge_context["expected_answer"] = case.expected_answer
    context_value = json.dumps(judge_context, ensure_ascii=False, separators=(",", ":"))
    if len(context_value) > 20_000:
        return {"status": "unscored", "reason_code": "JUDGE_INPUT_LIMIT"}
    try:
        response = get_model_provider().generate(
            prompt=prompt,
            context=[
                RetrievedChunk(
                    text=context_value,
                    source_id=f"question-case:{case.case_id}",
                    source_uri="evaluation:untrusted",
                )
            ],
            model_profile=run.judge_model_profile.body,
        )
        parsed = json.loads(response.text)
    except (ModelProviderError, json.JSONDecodeError, TypeError):
        return {"status": "unscored", "reason_code": "JUDGE_PROVIDER_FAILED"}
    verdict = parsed.get("verdict") if isinstance(parsed, dict) else None
    if verdict not in {"pass", "fail"}:
        return {"status": "unscored", "reason_code": "JUDGE_RESPONSE_INVALID"}
    return {
        "status": "scored",
        "verdict": verdict,
        "reason_code": "JUDGE_PASS" if verdict == "pass" else "JUDGE_FAIL",
        "model_checksum": run.judge_model_profile.checksum,
        "prompt_checksum": run.judge_prompt_contract.checksum,
    }


@transaction.atomic
def _retrieval_case(run: QuestionEvaluationRun, case: QuestionCase) -> QuestionEvaluationEvidence:
    set_tenant_context(run.organization_id)
    if (
        run.document_set_version is None
        or run.index_version is None
        or run.retrieval_profile is None
    ):
        raise QuestionEvaluationError("RETRIEVAL_PROVENANCE_INCOMPLETE")
    chunks = get_retrieval_provider().retrieve(
        query=case.question,
        profile=run.retrieval_profile.body,
        organization_id=run.organization_id,
        index_versions=[run.index_version.pk],
        document_set_version_ids=[run.document_set_version.pk],
        operator_test=True,
    )
    scoring, evidence = score_retrieval(case.expected_anchors, chunks)
    if scoring["hit"] is None:
        status = QuestionEvaluationEvidenceStatus.UNSCORED
        passed: bool | None = None
    else:
        passed = bool(scoring["hit"])
        status = (
            QuestionEvaluationEvidenceStatus.PASSED
            if passed
            else QuestionEvaluationEvidenceStatus.FAILED
        )
    return QuestionEvaluationEvidence.objects.create(
        organization_id=run.organization_id,
        run=run,
        question_case=case,
        ordinal=case.ordinal,
        status=status,
        passed=passed,
        retrieval_evidence=evidence,
        assertions=[{"type": "retrieval", **scoring}],
    )


def require_real_model_provider(release: ScenarioRelease) -> None:
    """Refuse an operator test that would return a deterministic placeholder as an answer.

    ``RUNTIME_MODEL_PROVIDER`` is empty by default, so ``get_model_provider()`` returns the
    deterministic stub and a generating workflow still answers — convincingly, but with text
    no model produced. That is fine for hermetic tests and for the governed evaluation gate,
    and misleading for a human asking the scenario a question, so this check is scoped to the
    operator one-off surface only.
    """

    from apps.releases.lifecycle import release_generates_text

    if not getattr(settings, "RUNTIME_MODEL_PROVIDER", "") and release_generates_text(release):
        raise QuestionEvaluationError("MODEL_PROVIDER_NOT_CONFIGURED")


def scenario_question_payload(question: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the runtime input envelope for one operator question.

    The canonical scenario input contract is ``{"query": ...}`` with no additional
    properties (``apps.console.scenario_defaults``), and the workflow reads exactly
    ``input["query"]`` (``apps.workflows.runtime._workflow_query``). Sending ``question``
    instead silently produced an empty query, so every answer came back generic.

    An explicit case ``input`` wins, so a question set can still shape its own envelope.
    """

    payload = dict(base or {})
    payload.setdefault("query", question)
    return payload


def _answer_case(run: QuestionEvaluationRun, case: QuestionCase) -> QuestionEvaluationEvidence:
    with transaction.atomic():
        set_tenant_context(run.organization_id)
        release = run.release
        if release is None:
            raise QuestionEvaluationError("ANSWER_PROVENANCE_INCOMPLETE")
    payload = scenario_question_payload(case.question, case.input_payload)
    result = execute_release_input(
        release=release,
        input_payload=payload,
        request_key=f"question-eval:{run.pk}:{case.ordinal}",
    )
    return _record_answer_case(run, case, result)


@transaction.atomic
def _record_answer_case(
    run: QuestionEvaluationRun, case: QuestionCase, result: Any
) -> QuestionEvaluationEvidence:
    set_tenant_context(run.organization_id)
    answer = _answer_text(result.output)
    if len(answer) > MAX_ANSWER_CHARS:
        raise QuestionEvaluationError("ANSWER_LIMIT_EXCEEDED")
    outcomes = evaluate_answer_assertions(case.assertions, result.output)
    judge = _judge_case(run=run, case=case, answer=answer)
    applicable = bool(outcomes)
    passed = all(item["passed"] for item in outcomes) if applicable else None
    if case.judge_policy.get("required"):
        if judge.get("status") != "scored":
            passed = None
        else:
            applicable = True
            passed = bool(passed is not False and judge.get("verdict") == "pass")
    if passed is None:
        status = QuestionEvaluationEvidenceStatus.UNSCORED
    else:
        status = (
            QuestionEvaluationEvidenceStatus.PASSED
            if passed
            else QuestionEvaluationEvidenceStatus.FAILED
        )
    return QuestionEvaluationEvidence.objects.create(
        organization_id=run.organization_id,
        run=run,
        question_case=case,
        ordinal=case.ordinal,
        status=status,
        passed=passed,
        generated_answer=answer,
        assertions=outcomes,
        judge=judge,
    )


def _aggregate_run(run: QuestionEvaluationRun) -> None:
    # Query the table, not ``run.case_evidence``: the worker loads the run with
    # ``prefetch_related("case_evidence")`` *before* any case has run, so the related
    # manager's cache is an empty list captured at load time. Reading it here made every
    # completed run report 0 passed / 0 completed with null metrics, no matter what the
    # evidence rows actually said.
    evidence = list(QuestionEvaluationEvidence.objects.filter(run=run).order_by("ordinal"))
    run.completed_cases = len(evidence)
    run.passed_cases = sum(
        item.status == QuestionEvaluationEvidenceStatus.PASSED for item in evidence
    )
    run.unscored_cases = sum(
        item.status == QuestionEvaluationEvidenceStatus.UNSCORED for item in evidence
    )
    run.error_cases = sum(
        item.status == QuestionEvaluationEvidenceStatus.ERROR for item in evidence
    )
    if run.kind == QuestionEvaluationKind.RETRIEVAL:
        scored = [
            item.assertions[0]
            for item in evidence
            if item.assertions and item.assertions[0].get("hit") is not None
        ]
        denominator = len(scored)
        run.metrics = {
            "retrieval_denominator": denominator,
            "unscored": run.unscored_cases,
            "hit_at_k": (
                sum(float(item["hit"]) for item in scored) / denominator if denominator else None
            ),
            "recall_at_k": (
                sum(float(item["recall"]) for item in scored) / denominator if denominator else None
            ),
            "mrr": (
                sum(float(item["reciprocal_rank"]) for item in scored) / denominator
                if denominator
                else None
            ),
        }
    else:
        scored_count = sum(item.passed is not None for item in evidence)
        judge_scored = sum(item.judge.get("status") == "scored" for item in evidence)
        judge_passed = sum(item.judge.get("verdict") == "pass" for item in evidence)
        run.metrics = {
            "answer_denominator": scored_count,
            "answer_pass_rate": run.passed_cases / scored_count if scored_count else None,
            "unscored": run.unscored_cases,
            "judge_denominator": judge_scored,
            "judge_pass_rate": judge_passed / judge_scored if judge_scored else None,
        }


def execute_question_evaluation(*, run: QuestionEvaluationRun) -> QuestionEvaluationRun:
    """Own one delivery while each execution and evidence transaction commits independently."""
    with question_evaluation_lock(run.organization_id, run.pk) as acquired:
        if not acquired:
            return run
        return _execute_question_evaluation(run=run)


def _execute_question_evaluation(*, run: QuestionEvaluationRun) -> QuestionEvaluationRun:
    with transaction.atomic():
        set_tenant_context(run.organization_id)
        run.refresh_from_db()
        if run.status in {
            QuestionEvaluationStatus.COMPLETED,
            QuestionEvaluationStatus.FAILED,
            QuestionEvaluationStatus.CANCELLED,
        }:
            return run
        run.status = QuestionEvaluationStatus.RUNNING
        run.error_code = ""
        run.save(update_fields=["status", "error_code", "updated_at"])
        cases = list(run.question_set_version.cases.order_by("ordinal")[: MAX_CASES + 1])
        if len(cases) > MAX_CASES:
            raise QuestionEvaluationError("QUESTION_CASE_LIMIT_EXCEEDED")
    for case in cases:
        with transaction.atomic():
            set_tenant_context(run.organization_id)
            run.refresh_from_db(fields=["cancel_requested_at"])
            if run.cancel_requested_at is not None:
                run.status = QuestionEvaluationStatus.CANCELLED
                break
            if run.case_evidence.filter(question_case=case).exists():
                continue
        try:
            if run.kind == QuestionEvaluationKind.RETRIEVAL:
                evidence = _retrieval_case(run, case)
            else:
                evidence = _answer_case(run, case)
        except (QuestionEvaluationError, EvalError) as exc:
            with transaction.atomic():
                set_tenant_context(run.organization_id)
                code = exc.code
                evidence = QuestionEvaluationEvidence.objects.create(
                    organization_id=run.organization_id,
                    run=run,
                    question_case=case,
                    ordinal=case.ordinal,
                    status=QuestionEvaluationEvidenceStatus.ERROR,
                    passed=None,
                    error_code=code,
                )
        except Exception:
            with transaction.atomic():
                set_tenant_context(run.organization_id)
                evidence = QuestionEvaluationEvidence.objects.create(
                    organization_id=run.organization_id,
                    run=run,
                    question_case=case,
                    ordinal=case.ordinal,
                    status=QuestionEvaluationEvidenceStatus.ERROR,
                    passed=None,
                    error_code="INTERNAL_ERROR",
                )
        QUESTION_EVAL_CASES.labels(kind=run.kind, status=evidence.status).inc()
    with transaction.atomic():
        set_tenant_context(run.organization_id)
        # Cancellation may arrive while the last case is executing. Serialize
        # finalization with the canonical cancellation writer before choosing status.
        cancellation = (
            QuestionEvaluationRun.objects.select_for_update()
            .get(pk=run.pk, organization_id=run.organization_id)
            .cancel_requested_at
        )
        if cancellation is not None:
            run.status = QuestionEvaluationStatus.CANCELLED
        _aggregate_run(run)
        if run.status != QuestionEvaluationStatus.CANCELLED:
            run.status = (
                QuestionEvaluationStatus.FAILED
                if run.error_cases == run.total_cases and run.total_cases > 0
                else QuestionEvaluationStatus.COMPLETED
            )
        run.finished_at = timezone.now()
        run.error_code = "ALL_CASES_ERROR" if run.status == QuestionEvaluationStatus.FAILED else ""
        run.save(
            update_fields=[
                "status",
                "completed_cases",
                "passed_cases",
                "unscored_cases",
                "error_cases",
                "metrics",
                "finished_at",
                "error_code",
                "updated_at",
            ]
        )
        QUESTION_EVAL_RUNS.labels(kind=run.kind, status=run.status).inc()
        QUESTION_EVAL_DURATION.labels(kind=run.kind).observe(
            max(0.0, (run.finished_at - run.created_at).total_seconds())
        )
        _audit_run(run, action="completed", actor_id="evaluation-worker")
        return run


@transaction.atomic
def request_evaluation_cancellation(
    *, run: QuestionEvaluationRun, user: Any, request_id: str = ""
) -> QuestionEvaluationRun:
    if run.kind == QuestionEvaluationKind.RETRIEVAL:
        target = run.document_set_version
        allowed = bool(
            target
            and authorize(
                user=user,
                capability=Capability.DOCUMENT_SET_OPERATIONS_MANAGE,
                organization=run.organization,
                document_set=target.document_set,
            ).allowed
        )
    else:
        allowed = bool(
            run.release
            and authorize(
                user=user,
                capability=Capability.SCENARIO_TEST,
                organization=run.organization,
                project=run.release.scenario.project,
                scenario=run.release.scenario,
            ).allowed
        )
    if not allowed:
        raise QuestionEvaluationError("EVALUATION_CANCEL_AUTHORIZATION_DENIED")
    locked = QuestionEvaluationRun.objects.select_for_update().get(pk=run.pk)
    if locked.status not in {
        QuestionEvaluationStatus.QUEUED,
        QuestionEvaluationStatus.RUNNING,
    }:
        return locked
    locked.cancel_requested_at = timezone.now()
    locked.save(update_fields=["cancel_requested_at", "updated_at"])
    _audit_run(locked, action="cancel_requested", actor_id=str(user.pk), request_id=request_id)
    return locked


@transaction.atomic
def _audit_probe(
    *,
    action: str,
    organization_id: int,
    actor_id: str,
    resource_type: str,
    resource_id: str,
    allowed: bool,
    request_id: str,
    chunk_count: int | None = None,
    index_version_id: int | None = None,
) -> None:
    """Record an operator probe.

    A probe can surface document chunks to its caller, so who asked, against what, and whether
    it was allowed belong in the audit trail. The question, the answer and the chunk contents do
    not: the count is enough to see that content was exposed.
    """

    set_tenant_context(organization_id)
    after: dict[str, Any] = {}
    if chunk_count is not None:
        after["chunk_count"] = chunk_count
    if index_version_id is not None:
        after["index_version_id"] = index_version_id
    record_event(
        actor_type="user",
        actor_id=actor_id,
        action=action,
        outcome="success" if allowed else "deny",
        organization_id=organization_id,
        resource_type=resource_type,
        resource_id=resource_id,
        reason="allowed" if allowed else "authorization_denied",
        request_id=request_id,
        after=after or None,
    )


def ask_document_set_once(
    *,
    user: Any,
    document_set_version: DocumentSetVersion,
    index_version: IndexVersion,
    profile_body: dict[str, Any],
    question: str,
    request_id: str = "",
) -> OneOffResult:
    """Probe one index with a query. The caller owns the settings; nothing is persisted.

    Takes a body rather than an artifact because the provider was only ever given a body, and
    because a document set no longer owns a retrieval profile -- query-time retrieval belongs
    to the scenario's ``retrieve`` node. This probe answers whether the *index* works.
    """

    decision = authorize(
        user=user,
        capability=Capability.DOCUMENT_SET_OPERATIONS_MANAGE,
        organization=document_set_version.organization,
        document_set=document_set_version.document_set,
    )
    if not decision.allowed:
        _audit_probe(
            action="evaluation.document_set.probe",
            organization_id=document_set_version.organization_id,
            actor_id=str(user.pk),
            resource_type="document_set_version",
            resource_id=str(document_set_version.pk),
            allowed=False,
            request_id=request_id,
        )
        raise QuestionEvaluationError("RETRIEVAL_EVALUATION_AUTHORIZATION_DENIED")
    query = _bounded_string(question, maximum=MAX_QUESTION_CHARS, code="QUESTION_TEXT_INVALID")
    chunks = get_retrieval_provider().retrieve(
        query=query,
        profile=profile_body,
        organization_id=document_set_version.organization_id,
        index_versions=[index_version.pk],
        document_set_version_ids=[document_set_version.pk],
        operator_test=True,
    )
    _audit_probe(
        action="evaluation.document_set.probe",
        organization_id=document_set_version.organization_id,
        actor_id=str(user.pk),
        resource_type="document_set_version",
        resource_id=str(document_set_version.pk),
        allowed=True,
        request_id=request_id,
        chunk_count=len(chunks),
        index_version_id=index_version.pk,
    )
    return OneOffResult(answer="", chunks=chunks)


def scenario_retrieval_evidence(*, result: Any) -> list[RetrievedChunk]:
    """Pair a run's citations with its numeric chunk pointers. Carries no document text.

    ``sources`` and the state's chunk list are produced one-to-one by the same projection, so
    they align by position when the model cites exactly what it was given. If they ever do not,
    a pointer is never attributed to the wrong source -- guessing would be worse than showing
    none. BUG-012: that safety property used to also throw away every pointer outright, so a
    misaligned answer showed zero real chunk text even to a fully authorized reader. The raw,
    unattributed pointers are now still returned (``chunk_kind="unattributed"``) after the
    per-source list, so the console can render them as "fetched but not matched to a citation"
    instead of silently dropping real, resolvable evidence.
    """

    sources = _sources(result.output)
    raw = result.metadata.get("retrieval") if isinstance(result.metadata, dict) else None
    pointers = raw if isinstance(raw, list) else []
    if not sources:
        return []
    misaligned = len(pointers) != len(sources)
    aligned: list[Any] = [{}] * len(sources) if misaligned else pointers
    chunks: list[RetrievedChunk] = []
    for source, pointer in zip(sources[:MAX_EVIDENCE_CHUNKS], aligned, strict=False):
        if not isinstance(source, dict):
            continue
        safe = pointer if isinstance(pointer, dict) else {}
        chunks.append(
            RetrievedChunk(
                text="",
                source_id=str(source.get("source_id") or ""),
                source_uri=str(source.get("source_uri") or ""),
                title=str(source.get("title") or ""),
                score=_as_float(source.get("score")),
                document_version_id=_as_int(safe.get("document_version_id")),
                index_version_id=_as_int(safe.get("index_version_id")),
                ordinal=_as_int(safe.get("ordinal")),
            )
        )
    if misaligned:
        remaining = MAX_EVIDENCE_CHUNKS - len(chunks)
        for pointer in pointers[: max(remaining, 0)]:
            if not isinstance(pointer, dict):
                continue
            chunks.append(
                RetrievedChunk(
                    text="",
                    source_id="",
                    source_uri="",
                    chunk_kind="unattributed",
                    document_version_id=_as_int(pointer.get("document_version_id")),
                    index_version_id=_as_int(pointer.get("index_version_id")),
                    ordinal=_as_int(pointer.get("ordinal")),
                )
            )
    return chunks


def resolve_chunk_text(
    *,
    user: Any,
    organization_id: int,
    index_version_id: Any,
    document_version_id: Any,
    ordinal: Any,
) -> str:
    """Resolve one chunk's text, or "" when the operator may not read document content.

    Asking a scenario a question needs ``SCENARIO_TEST``. Reading what a document actually said
    is a document-plane right, checked separately against the set that owns the index, so a
    scenario editor without it sees where an answer came from and not what the source said.

    Text is never carried in a session or a run projection; it is resolved here, against the
    live authorization, each time it is displayed.
    """

    index_pk = _as_int(index_version_id)
    document_pk = _as_int(document_version_id)
    chunk_ordinal = _as_int(ordinal)
    if index_pk is None or document_pk is None or chunk_ordinal is None:
        return ""
    index_version = (
        IndexVersion.objects.select_related("document_set_version__document_set")
        .filter(pk=index_pk, organization_id=organization_id)
        .first()
    )
    set_version = index_version.document_set_version if index_version else None
    if index_version is None or set_version is None:
        return ""
    if not authorize(
        user=user,
        capability=Capability.DOCUMENT_SET_CONTENT_READ,
        organization=index_version.organization,
        document_set=set_version.document_set,
    ).allowed:
        return ""
    try:
        return exact_chunk_text(index_version, document_pk, chunk_ordinal) or ""
    except VectorStoreError:
        return ""


def _as_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def ask_scenario_once(
    *, user: Any, release: ScenarioRelease, question: str, request_id: str = ""
) -> OneOffResult:
    with operator_transaction(user):
        decision = authorize(
            user=user,
            capability=Capability.SCENARIO_TEST,
            organization=release.organization,
            project=release.scenario.project,
            scenario=release.scenario,
        )
        if not decision.allowed:
            _audit_probe(
                action="evaluation.scenario.probe",
                organization_id=release.organization_id,
                actor_id=str(user.pk),
                resource_type="scenario_release",
                resource_id=str(release.pk),
                allowed=False,
                request_id=request_id,
            )
            raise QuestionEvaluationError("ANSWER_EVALUATION_AUTHORIZATION_DENIED")
        query = _bounded_string(question, maximum=MAX_QUESTION_CHARS, code="QUESTION_TEXT_INVALID")
        require_real_model_provider(release)
    result = execute_release_input(
        release=release,
        input_payload=scenario_question_payload(query),
        request_key=f"one-off:{release.pk}:{hashlib.sha256(query.encode()).hexdigest()[:24]}",
    )
    answer = _answer_text(result.output)
    if len(answer) > MAX_ANSWER_CHARS:
        raise QuestionEvaluationError("ANSWER_LIMIT_EXCEEDED")
    chunks = scenario_retrieval_evidence(result=result)
    _audit_probe(
        action="evaluation.scenario.probe",
        organization_id=release.organization_id,
        actor_id=str(user.pk),
        resource_type="scenario_release",
        resource_id=str(release.pk),
        allowed=True,
        request_id=request_id,
        chunk_count=len(chunks),
    )
    return OneOffResult(answer=answer, chunks=chunks)


@transaction.atomic
def purge_expired_question_evidence(
    *, organization: Any, actor: str, now: Any | None = None, request_id: str = ""
) -> int:
    """Redact expired confidential evidence while retaining immutable scoring provenance."""

    cutoff = now or timezone.now()
    runs = QuestionEvaluationRun.objects.filter(
        organization=organization,
        legal_hold=False,
        retention_until__isnull=False,
        retention_until__lte=cutoff,
    )
    evidence = QuestionEvaluationEvidence.objects.filter(run__in=runs).exclude(
        generated_answer="", retrieval_evidence=[]
    )
    count = evidence.update(generated_answer="", retrieval_evidence=[])
    if count:
        record_event(
            actor_type="system",
            actor_id=actor,
            action="evaluation.question_evidence.retention_redacted",
            outcome="success",
            organization_id=organization.pk,
            resource_type="question_evaluation_evidence",
            resource_id="retention-batch",
            reason="retention_expired",
            request_id=request_id,
            after={"count": count},
        )
    return count
