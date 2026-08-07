"""Operator questions must actually reach the workflow, and must not be answered by a stub.

Both operator question paths sent ``{"question": ...}`` while the workflow reads
``input["query"]`` and the canonical input contract forbids extra properties, so every
answer was produced from an empty query.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.evaluations.question_services import (
    QuestionEvaluationError,
    release_generates_text,
    require_real_model_provider,
    scenario_question_payload,
)
from apps.releases.models import ScenarioRelease
from apps.workflows.runtime import _workflow_query

pytestmark = pytest.mark.django_db


def test_the_question_lands_on_the_key_the_workflow_reads() -> None:
    payload = scenario_question_payload("Kargo ne zaman gelir?")

    assert payload == {"query": "Kargo ne zaman gelir?"}
    # The exact accessor the runtime uses; a key rename here would silently empty the query.
    assert _workflow_query({"input": payload}) == "Kargo ne zaman gelir?"


def test_the_payload_satisfies_the_canonical_input_contract() -> None:
    import jsonschema

    from apps.artifacts.types import ArtifactType
    from apps.console.scenario_defaults import default_contract_body

    jsonschema.validate(
        scenario_question_payload("Soru"),
        default_contract_body(ArtifactType.INPUT_CONTRACT),
    )


def test_an_explicit_case_envelope_still_wins() -> None:
    payload = scenario_question_payload("varsayılan", {"query": "elle yazılmış"})

    assert payload["query"] == "elle yazılmış"


class _Graph:
    def __init__(self, node_types: list[str]) -> None:
        self.compiled_graph = {"nodes": [{"id": t, "type": t} for t in node_types]}


def _release() -> ScenarioRelease:
    """Only identity matters here; the workflow lookup is patched per test."""

    return ScenarioRelease()


@pytest.mark.parametrize(
    ("node_types", "generates"),
    [
        (["input", "generate", "end"], True),
        (["input", "agent_loop", "end"], True),
        (["input", "retrieve", "format_output", "end"], False),
    ],
)
def test_generating_workflows_are_detected(
    monkeypatch: pytest.MonkeyPatch, node_types: list[str], generates: bool
) -> None:
    monkeypatch.setattr(
        "apps.workflows.services.resolve_release_workflow",
        lambda release: _Graph(node_types),
    )

    assert release_generates_text(_release()) is generates


@override_settings(RUNTIME_MODEL_PROVIDER="")
def test_a_generating_release_refuses_to_answer_from_the_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.workflows.services.resolve_release_workflow",
        lambda release: _Graph(["input", "generate", "end"]),
    )

    with pytest.raises(QuestionEvaluationError) as excinfo:
        require_real_model_provider(_release())

    assert excinfo.value.code == "MODEL_PROVIDER_NOT_CONFIGURED"


@override_settings(RUNTIME_MODEL_PROVIDER="apps.orchestration.providers.StubModelProvider")
def test_a_configured_provider_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.workflows.services.resolve_release_workflow",
        lambda release: _Graph(["input", "generate", "end"]),
    )

    require_real_model_provider(_release())


@override_settings(RUNTIME_MODEL_PROVIDER="")
def test_a_non_generating_release_needs_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.workflows.services.resolve_release_workflow",
        lambda release: _Graph(["input", "retrieve", "end"]),
    )

    require_real_model_provider(_release())
