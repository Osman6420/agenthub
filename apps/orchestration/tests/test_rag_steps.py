"""Shared governed retrieve/generate steps used by the workflow + agent runtimes (P5)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from apps.orchestration import rag_steps
from apps.retrieval.types import RetrievedChunk


def _fake_bundle(**overrides: Any) -> SimpleNamespace:
    base = {
        "retrieval_profile": {},
        "data_selection": "legacy_pinned",
        "organization_id": 1,
        "scenario_id": 2,
        "index_versions": [],
        "document_set_version_ids": [],
        "prompt_text": "system prompt",
        "model_profile": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_chunks_roundtrip_through_state() -> None:
    chunk = RetrievedChunk(
        text="t",
        source_id="s",
        source_uri="u",
        title="Ti",
        score=0.9,
        chunk_kind="content",
        keyword_rank=1,
        keyword_score=0.8,
        document_routing_score=0.7,
        retrieval_stage="summary_routed",
    )
    state = {"retrieval": {"chunks": [rag_steps.chunk_to_dict(chunk)]}}
    rebuilt = rag_steps.chunks_from_state(state)
    assert len(rebuilt) == 1
    assert rebuilt[0].text == "t" and rebuilt[0].score == 0.9
    assert rebuilt[0].keyword_rank == 1
    assert rebuilt[0].document_routing_score == 0.7
    assert rebuilt[0].retrieval_stage == "summary_routed"


def test_chunks_from_state_tolerates_missing_or_malformed() -> None:
    assert rag_steps.chunks_from_state({}) == []
    assert rag_steps.chunks_from_state({"retrieval": {"chunks": ["nope", {"no_text": 1}]}}) == []


def test_retrieve_for_release_uses_release_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    # The demo provider returns a canned grounded passage regardless of scope.
    monkeypatch.setattr(rag_steps, "resolve_bundle", lambda release: _fake_bundle())
    monkeypatch.setenv("PYTEST_UNUSED", "1")
    monkeypatch.setattr(
        rag_steps,
        "get_retrieval_provider",
        lambda: __import__(
            "apps.retrieval.providers", fromlist=["DemoRetrievalProvider"]
        ).DemoRetrievalProvider(),
    )
    block = rag_steps.retrieve_for_release(release=object(), query="iade")
    assert block["chunks"] and block["top_score"] > 0
    assert "text" in block["chunks"][0] and "score" in block["chunks"][0]


def test_retrieve_for_release_uses_explicit_node_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Provider:
        def retrieve(self, **kwargs: Any) -> list[RetrievedChunk]:
            captured.update(kwargs)
            return []

    monkeypatch.setattr(
        rag_steps,
        "resolve_bundle",
        lambda release: _fake_bundle(retrieval_profile={"top_k": 2}),
    )
    monkeypatch.setattr(rag_steps, "get_retrieval_provider", lambda: _Provider())

    rag_steps.retrieve_for_release(
        release=object(),
        query="iade",
        retrieval_profile={"mode": "hybrid", "top_k": 17},
    )

    assert captured["profile"] == {"mode": "hybrid", "top_k": 17}


def test_generate_for_release_grounds_on_context(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default StubModelProvider echoes the top retrieved chunk, proving the context is passed.
    monkeypatch.setattr(rag_steps, "resolve_bundle", lambda release: _fake_bundle())
    context = [RetrievedChunk(text="grounded answer", source_id="s", source_uri="u", score=1.0)]
    response = rag_steps.generate_for_release(release=object(), context=context)
    assert response.text == "grounded answer"


def test_generate_for_release_defaults_to_bundle_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Provider:
        def generate(self, *, prompt: str, context: Any, model_profile: Any) -> Any:
            captured["prompt"] = prompt
            captured["model_profile"] = model_profile
            return SimpleNamespace(text="ok", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(
        rag_steps,
        "resolve_bundle",
        lambda release: _fake_bundle(prompt_text="P", model_profile={"m": 1}),
    )
    monkeypatch.setattr(rag_steps, "get_model_provider", lambda: _Provider())
    rag_steps.generate_for_release(release=object(), context=[])  # no override -> bundle defaults
    assert captured == {"prompt": "P", "model_profile": {"m": 1}}


def test_generate_for_release_forwards_user_query_as_untrusted_model_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _Provider:
        def generate(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(text="ok", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(rag_steps, "resolve_bundle", lambda release: _fake_bundle())
    monkeypatch.setattr(rag_steps, "get_model_provider", lambda: _Provider())

    rag_steps.generate_for_release(release=object(), context=[], user_query="Untrusted question")

    assert captured["user_query"] == "Untrusted question"


def test_generate_for_release_keeps_legacy_provider_signature_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _LegacyProvider:
        def generate(self, *, prompt: str, context: Any, model_profile: Any) -> Any:
            captured.update(prompt=prompt, context=context, model_profile=model_profile)
            return SimpleNamespace(text="ok", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(rag_steps, "resolve_bundle", lambda release: _fake_bundle())
    monkeypatch.setattr(rag_steps, "get_model_provider", lambda: _LegacyProvider())

    rag_steps.generate_for_release(release=object(), context=[], user_query="Untrusted question")

    assert set(captured) == {"prompt", "context", "model_profile"}
