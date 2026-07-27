"""RAG governance parity across the three runtimes.

``run_rag`` (synchronous), the workflow ``generate`` node and the agent ``_respond`` step must
enforce the *same* two invariants, or a Document Answer scenario would leak more through a workflow
than through a direct query:

* citations carry provenance only — retrieved document text never reaches a caller;
* a policy that requires grounding refuses to call the model at all and returns the
  release-pinned fallback answer.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from apps.agents.runtime import _respond
from apps.orchestration import rag_steps
from apps.orchestration.rag_steps import DEFAULT_FALLBACK_ANSWER
from apps.workflows.runtime import _execute_eligible_node

GROUNDED = {
    "retrieval": {
        "chunks": [
            {
                "text": "confidential contract clause",
                "source_id": "s1",
                "source_uri": "u1",
                "title": "T1",
                "score": 0.9,
            }
        ],
        "top_score": 0.9,
    }
}


def _bundle(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "policy": {},
        "prompt_text": "system prompt",
        "model_profile": {},
        "retrieval_profile": {},
        "organization_id": 1,
        "scenario_id": 2,
        "index_versions": [],
        "document_set_version_ids": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _pin(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    monkeypatch.setattr(rag_steps, "resolve_bundle", lambda release: _bundle(**overrides))


class _Echo:
    def generate(self, *, prompt: str, context: Any, model_profile: Any) -> Any:
        return SimpleNamespace(text="generated", input_tokens=3, output_tokens=4)


class _NeverCalled:
    def generate(self, **_: object) -> object:
        raise AssertionError("the model was called for an ungrounded request")


# --- citation projection -------------------------------------------------------------------


def test_citations_carry_provenance_without_document_text() -> None:
    assert rag_steps.citations_from_state(GROUNDED) == [
        {"source_id": "s1", "source_uri": "u1", "title": "T1", "score": 0.9}
    ]


def test_citations_tolerate_missing_or_malformed_state() -> None:
    assert rag_steps.citations_from_state({}) == []
    assert rag_steps.citations_from_state({"retrieval": {"chunks": "nope"}}) == []
    assert rag_steps.citations_from_state({"retrieval": {"chunks": ["nope"]}}) == []


# --- grounding gate ------------------------------------------------------------------------


def test_grounding_gate_is_inert_without_a_requiring_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(monkeypatch)
    assert rag_steps.grounding_fallback_answer(release=object(), state={}) is None


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"retrieval": {"chunks": [], "top_score": 0.0}},
        {"retrieval": {"chunks": [{"source_id": "s"}], "top_score": 0.2}},
        {"retrieval": {"chunks": [{"source_id": "s"}], "top_score": "not-a-number"}},
    ],
)
def test_grounding_gate_falls_back_when_the_floor_is_not_cleared(
    monkeypatch: pytest.MonkeyPatch, state: dict[str, Any]
) -> None:
    _pin(
        monkeypatch,
        policy={
            "grounding": {"required": True, "min_top_score": 0.45},
            "fallback": {"answer": "pinned fallback"},
        },
    )
    assert rag_steps.grounding_fallback_answer(release=object(), state=state) == "pinned fallback"


def test_grounding_gate_defaults_to_the_platform_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin(monkeypatch, policy={"grounding": {"required": True, "min_top_score": 0.45}})
    assert (
        rag_steps.grounding_fallback_answer(release=object(), state={}) == DEFAULT_FALLBACK_ANSWER
    )


def test_grounding_gate_passes_above_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin(monkeypatch, policy={"grounding": {"required": True, "min_top_score": 0.45}})
    assert rag_steps.grounding_fallback_answer(release=object(), state=GROUNDED) is None


# --- workflow generate node ----------------------------------------------------------------


def _generate_node() -> dict[str, Any]:
    return {"id": "g", "type": "generate", "config": {}}


def _run() -> SimpleNamespace:
    return SimpleNamespace(release=object(), consumer_id=None)


def test_workflow_generate_redacts_document_text_from_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(monkeypatch)
    monkeypatch.setattr(rag_steps, "get_model_provider", lambda: _Echo())
    envelope = _execute_eligible_node(
        node=_generate_node(), state=dict(GROUNDED), input_env=None, run=_run()
    )
    assert envelope == {
        "answer": "generated",
        "sources": [{"source_id": "s1", "source_uri": "u1", "title": "T1", "score": 0.9}],
    }


def test_workflow_generate_never_calls_the_model_when_ungrounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(
        monkeypatch,
        policy={
            "grounding": {"required": True, "min_top_score": 0.99},
            "fallback": {"answer": "pinned fallback"},
        },
    )
    monkeypatch.setattr(rag_steps, "get_model_provider", lambda: _NeverCalled())
    envelope = _execute_eligible_node(
        node=_generate_node(), state=dict(GROUNDED), input_env=None, run=_run()
    )
    assert envelope == {"answer": "pinned fallback", "sources": []}


# --- agent respond step --------------------------------------------------------------------


def test_agent_respond_redacts_document_text_from_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin(monkeypatch)
    monkeypatch.setattr(rag_steps, "get_model_provider", lambda: _Echo())
    output, input_tokens, output_tokens = _respond("q", dict(GROUNDED), {}, object())
    assert output == {
        "answer": "generated",
        "sources": [{"source_id": "s1", "source_uri": "u1", "title": "T1", "score": 0.9}],
    }
    assert (input_tokens, output_tokens) == (3, 4)


def test_agent_respond_never_calls_the_model_when_ungrounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(
        monkeypatch,
        policy={
            "grounding": {"required": True, "min_top_score": 0.99},
            "fallback": {"answer": "pinned fallback"},
        },
    )
    monkeypatch.setattr(rag_steps, "get_model_provider", lambda: _NeverCalled())
    output, input_tokens, output_tokens = _respond("q", dict(GROUNDED), {}, object())
    assert output == {"answer": "pinned fallback", "sources": []}
    # A refused generation must not be billed as model usage.
    assert (input_tokens, output_tokens) == (0, 0)
