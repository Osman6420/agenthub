"""Scenario-owned test questions feed two governed consumers with different vocabularies."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import override_settings

from apps.artifacts.eval_suite import validate_eval_suite_body
from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, Scenario
from apps.evaluations.models import QuestionSet
from apps.evaluations.scenario_questions import (
    JUDGE_PROMPT_TEMPLATE,
    MODE_CONTAINS,
    MODE_EXACT,
    MODE_JUDGE,
    ScenarioQuestionError,
    build_eval_suite_body,
    get_judge_artifacts,
    judge_readiness,
    judge_target_release,
    load_rows,
    normalize_rows,
    save_scenario_test_questions,
    set_judge_model,
    start_judged_evaluation,
)
from apps.orchestration.models import ModelProfile, ModelProfileStatus
from apps.releases.scenario_artifacts import scenario_artifact_logical_id
from apps.tenancy.models import Organization

pytestmark = pytest.mark.django_db


@pytest.fixture
def scenario() -> Scenario:
    org = Organization.objects.create(slug="tq-org", name="TQ")
    project = AIProject.objects.create(organization=org, slug="p", name="P")
    return Scenario.objects.create(organization=org, project=project, slug="s", name="S")


def _rows() -> list[dict]:
    return [
        {"question": "Kargo ne zaman gelir?", "mode": MODE_CONTAINS, "expected": "3 iş günü"},
        {"question": "İade süresi?", "mode": MODE_EXACT, "expected": "14 gün"},
        {"question": "Nasıl iade ederim?", "mode": MODE_JUDGE, "expected": "Adımları anlatmalı"},
    ]


def test_only_deterministic_rows_reach_the_promotion_gate() -> None:
    body = build_eval_suite_body(_rows())

    validate_eval_suite_body(body)
    # The exact-match and referee rows cannot be expressed in the closed allowlist, so the
    # gate must not silently claim to check them.
    assert [case["id"] for case in body["cases"]] == ["case-1"]
    assert body["cases"][0]["assertions"] == [{"type": "answer_contains", "value": "3 iş günü"}]
    assert body["cases"][0]["input"] == {"query": "Kargo ne zaman gelir?"}


def test_a_suite_is_never_empty_even_with_only_referee_rows() -> None:
    body = build_eval_suite_body(
        [{"question": "Bir soru", "mode": MODE_JUDGE, "expected": "iyi bir cevap"}]
    )

    validate_eval_suite_body(body)
    assert body["cases"][0]["assertions"] == [{"type": "workflow_completed"}]


def test_citation_requirement_is_carried_into_the_gate() -> None:
    body = build_eval_suite_body(
        [
            {
                "question": "Soru",
                "mode": MODE_CONTAINS,
                "expected": "cevap",
                "require_citation": True,
            }
        ]
    )

    validate_eval_suite_body(body)
    assert {"type": "citations_present"} in body["cases"][0]["assertions"]


def test_saving_publishes_the_suite_and_the_question_set(scenario: Scenario) -> None:
    result = save_scenario_test_questions(scenario=scenario, actor="editor", rows=_rows())

    assert result["eval_suite_changed"] is True
    suite = ArtifactVersion.objects.get(
        organization=scenario.organization,
        type=ArtifactType.EVAL_SUITE,
        logical_id=scenario_artifact_logical_id(scenario, ArtifactType.EVAL_SUITE),
    )
    assert suite.version == 1
    question_set = QuestionSet.objects.get(scenario=scenario)
    assert len(question_set.draft_cases) == 3
    modes = [case["judge"]["enabled"] for case in question_set.draft_cases]
    assert modes == [False, False, True]
    assert question_set.draft_cases[1]["assertions"] == [{"type": "exact", "value": "14 gün"}]


def test_saving_an_identical_body_does_not_mint_a_pointless_version(scenario: Scenario) -> None:
    save_scenario_test_questions(scenario=scenario, actor="editor", rows=_rows())
    second = save_scenario_test_questions(scenario=scenario, actor="editor", rows=_rows())

    assert second["eval_suite_changed"] is False
    assert (
        ArtifactVersion.objects.filter(
            organization=scenario.organization, type=ArtifactType.EVAL_SUITE
        ).count()
        == 1
    )


def test_rows_round_trip_back_into_the_editor(scenario: Scenario) -> None:
    save_scenario_test_questions(scenario=scenario, actor="editor", rows=_rows())

    loaded = load_rows(scenario)

    assert [row["question"] for row in loaded] == [row["question"] for row in _rows()]
    assert [row["mode"] for row in loaded] == [MODE_CONTAINS, MODE_EXACT, MODE_JUDGE]
    assert loaded[1]["expected"] == "14 gün"


def test_an_organization_wide_question_set_is_untouched(scenario: Scenario) -> None:
    shared = QuestionSet.objects.create(
        organization=scenario.organization,
        name="Paylaşılan set",
        draft_cases=[],
        created_by="admin",
        updated_by="admin",
    )

    save_scenario_test_questions(scenario=scenario, actor="editor", rows=_rows())

    shared.refresh_from_db()
    assert shared.scenario_id is None
    assert shared.draft_cases == []
    assert QuestionSet.objects.filter(scenario=scenario).count() == 1


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        ([], "TEST_QUESTION_COUNT_INVALID"),
        ([{"question": "", "mode": MODE_CONTAINS, "expected": "x"}], "TEST_QUESTION_TEXT_INVALID"),
        (
            [{"question": "Soru", "mode": "telepathy", "expected": "x"}],
            "TEST_QUESTION_MODE_INVALID",
        ),
        (
            [{"question": "Soru", "mode": MODE_CONTAINS, "expected": ""}],
            "TEST_QUESTION_EXPECTED_INVALID",
        ),
    ],
)
def test_invalid_rows_are_rejected_with_a_stable_code(rows: list[dict], code: str) -> None:
    with pytest.raises(ScenarioQuestionError) as excinfo:
        normalize_rows(rows)

    assert excinfo.value.code == code


def test_a_referee_row_keeps_its_expected_answer(scenario: Scenario) -> None:
    """Without this the referee never learns what the author was hoping for."""

    save_scenario_test_questions(scenario=scenario, actor="editor", rows=_rows())

    question_set = QuestionSet.objects.get(scenario=scenario)
    judge_case = question_set.draft_cases[2]
    assert judge_case["judge"] == {"enabled": True, "required": True}
    assert judge_case["expected_answer"] == "Adımları anlatmalı"
    # Deterministic rows carry assertions instead; their expected text is the assertion value.
    assert question_set.draft_cases[0]["expected_answer"] == ""

    assert load_rows(scenario)[2]["expected"] == "Adımları anlatmalı"


# --- LLM referee wiring ---------------------------------------------------------


def _catalog_profile(logical_id: str = "judge-gemini") -> ModelProfile:
    return ModelProfile.objects.create(
        logical_id=logical_id,
        revision=1,
        provider="openai_compatible",
        scheme="https",
        host="generativelanguage.googleapis.com",
        port=443,
        path="/v1beta/openai/chat/completions",
        model="gemini-3.6-flash",
        # A ``secret:<name>`` reference, resolved at egress time — never the credential.
        secret_ref="secret:gemini",  # noqa: S106
        timeout_seconds=30,
        max_response_bytes=200_000,
        max_output_tokens=1024,
        status=ModelProfileStatus.ACTIVE,
    )


@override_settings(EVALUATION_LLM_JUDGE_ENABLED=False)
def test_the_referee_reports_the_setting_gate_first(scenario: Scenario) -> None:
    """The flag is checked in ``_validate_judge_profiles``; pinning cannot substitute."""

    readiness = judge_readiness(scenario)

    assert readiness["ready"] is False
    assert "EVALUATION_LLM_JUDGE_ENABLED" in readiness["reason"]


@override_settings(EVALUATION_LLM_JUDGE_ENABLED=True)
def test_the_referee_reports_a_missing_model_before_claiming_ready(scenario: Scenario) -> None:
    readiness = judge_readiness(scenario)

    assert readiness["ready"] is False
    assert "Hakem modeli" in readiness["reason"]


@override_settings(EVALUATION_LLM_JUDGE_ENABLED=True)
def test_pinning_a_model_also_prepares_the_canonical_prompt(scenario: Scenario) -> None:
    profile = _catalog_profile()

    set_judge_model(scenario=scenario, actor="editor", profile_public_id=str(profile.public_id))

    model_artifact, prompt_artifact = get_judge_artifacts(scenario)
    assert model_artifact is not None and prompt_artifact is not None
    assert model_artifact.body == {"profile_id": str(profile.public_id)}
    assert prompt_artifact.body["template"] == JUDGE_PROMPT_TEMPLATE
    assert judge_readiness(scenario)["ready"] is True


@override_settings(EVALUATION_LLM_JUDGE_ENABLED=True)
def test_an_inactive_catalog_profile_is_refused(scenario: Scenario) -> None:
    profile = _catalog_profile()
    ModelProfile.objects.filter(pk=profile.pk).update(status=ModelProfileStatus.DISABLED)

    with pytest.raises(ScenarioQuestionError) as excinfo:
        set_judge_model(scenario=scenario, actor="editor", profile_public_id=str(profile.public_id))

    assert excinfo.value.code == "JUDGE_MODEL_UNAVAILABLE"


@override_settings(EVALUATION_LLM_JUDGE_ENABLED=True)
def test_repinning_the_same_model_mints_no_new_version(scenario: Scenario) -> None:
    profile = _catalog_profile()

    first = set_judge_model(
        scenario=scenario, actor="editor", profile_public_id=str(profile.public_id)
    )
    second = set_judge_model(
        scenario=scenario, actor="editor", profile_public_id=str(profile.public_id)
    )

    assert first.pk == second.pk


def test_the_judge_prompt_constrains_the_reply_to_a_parsable_verdict() -> None:
    """``_judge_case`` json-parses the reply and requires ``verdict`` in {pass, fail}."""

    assert json.dumps({"verdict": "pass"}, ensure_ascii=False).replace(" ", "") in (
        JUDGE_PROMPT_TEMPLATE.replace(" ", "")
    )
    assert json.dumps({"verdict": "fail"}, ensure_ascii=False).replace(" ", "") in (
        JUDGE_PROMPT_TEMPLATE.replace(" ", "")
    )
    # The answer under judgement is model output, so the instruction must say it is untrusted.
    assert "GÜVENİLMEZ" in JUDGE_PROMPT_TEMPLATE


@override_settings(EVALUATION_LLM_JUDGE_ENABLED=True)
def test_the_referee_is_shown_the_authors_expected_answer(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before ``QuestionCase.expected_answer`` existed the referee judged against nothing."""

    from apps.evaluations.models import QuestionCase, QuestionEvaluationRun
    from apps.evaluations.question_services import _judge_case
    from apps.orchestration.providers import ModelResponse

    profile = _catalog_profile()
    set_judge_model(scenario=scenario, actor="editor", profile_public_id=str(profile.public_id))
    model_artifact, prompt_artifact = get_judge_artifacts(scenario)

    seen: dict[str, object] = {}

    class _Provider:
        def generate(self, **kwargs: object) -> ModelResponse:
            seen.update(kwargs)
            return ModelResponse(text='{"verdict":"pass"}')

    monkeypatch.setattr(
        "apps.evaluations.question_services.get_model_provider", lambda: _Provider()
    )

    run = QuestionEvaluationRun(
        judge_model_profile=model_artifact,
        judge_prompt_contract=prompt_artifact,
    )

    case = QuestionCase(
        case_id="c1",
        question="İade süresi?",
        expected_answer="14 gün içinde iade edilebilir",
        judge_policy={"enabled": True, "required": True},
    )

    outcome = _judge_case(run=run, case=case, answer="İade 14 gün içinde yapılabilir.")

    assert outcome["status"] == "scored" and outcome["verdict"] == "pass"
    context_text = seen["context"][0].text  # type: ignore[index]
    assert "14 gün içinde iade edilebilir" in context_text
    assert seen["prompt"] == JUDGE_PROMPT_TEMPLATE
    assert seen["model_profile"] == {"profile_id": str(profile.public_id)}


def _tester(scenario: Scenario) -> Any:
    """A user with the exact scenario-editor authority ``SCENARIO_TEST`` requires."""

    from django.contrib.auth import get_user_model

    from apps.identity.models import ScenarioResponsibility, ScenarioResponsibilityAssignment
    from apps.tenancy.models import OrganizationMembership

    user = get_user_model().objects.create_user("tq-tester", password="x")  # noqa: S106
    membership = OrganizationMembership.objects.create(
        organization=scenario.organization, user=user
    )
    ScenarioResponsibilityAssignment.objects.create(
        organization=scenario.organization,
        membership=membership,
        scenario=scenario,
        responsibility=ScenarioResponsibility.EDITOR,
        assigned_by=user,
    )
    return user


def _release(scenario: Scenario, status: str) -> Any:
    from apps.releases.models import ScenarioRelease

    return ScenarioRelease.objects.create(
        organization=scenario.organization,
        scenario=scenario,
        status=status,
        runtime_version="runtime:v1",
        manifest={"artifacts": {}},
        artifact_manifest_sha256="0" * 64,
        created_by="editor",
    )


def test_evaluation_measures_the_candidate_not_the_promoted_release(scenario: Scenario) -> None:
    """Requiring an active release inverted the point of evaluating at all.

    An author had to publish a fix to production before being allowed to test whether the
    fix worked, so a corrected candidate could never be measured.
    """

    from apps.releases.models import ReleaseStatus

    active = _release(scenario, ReleaseStatus.ACTIVE)
    assert judge_target_release(scenario) == active

    candidate = _release(scenario, ReleaseStatus.CANDIDATE)

    assert judge_target_release(scenario) == candidate


def test_a_superseded_candidate_never_becomes_the_evaluation_target(scenario: Scenario) -> None:
    """Once the newest release is live, evaluation measures it — not older leftovers."""

    from apps.releases.models import ReleaseStatus

    _release(scenario, ReleaseStatus.CANDIDATE)
    promoted = _release(scenario, ReleaseStatus.ACTIVE)

    assert judge_target_release(scenario) == promoted


def test_without_any_release_evaluation_fails_closed(scenario: Scenario) -> None:
    assert judge_target_release(scenario) is None


@override_settings(EVALUATION_LLM_JUDGE_ENABLED=True)
def test_a_finished_evaluation_never_stands_in_for_a_new_one(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keying on the cases alone froze the verdict: clicking "evaluate" after fixing the
    flow returned the first, stale report instead of measuring again.
    """

    from apps.evaluations.models import QuestionEvaluationRun, QuestionEvaluationStatus
    from apps.releases.models import ReleaseStatus

    profile = _catalog_profile()
    set_judge_model(scenario=scenario, actor="editor", profile_public_id=str(profile.public_id))
    save_scenario_test_questions(scenario=scenario, actor="editor", rows=_rows())
    release = _release(scenario, ReleaseStatus.CANDIDATE)

    user = _tester(scenario)
    first = start_judged_evaluation(
        scenario=scenario, actor=user.get_username(), actor_id=str(user.pk), user=user
    )
    # An in-flight run absorbs a double submit rather than paying for a second set of calls.
    assert (
        start_judged_evaluation(
            scenario=scenario, actor=user.get_username(), actor_id=str(user.pk), user=user
        ).pk
        == first.pk
    )

    QuestionEvaluationRun.objects.filter(pk=first.pk).update(
        status=QuestionEvaluationStatus.COMPLETED
    )
    second = start_judged_evaluation(
        scenario=scenario, actor=user.get_username(), actor_id=str(user.pk), user=user
    )

    assert second.pk != first.pk
    assert second.release_id == release.pk
