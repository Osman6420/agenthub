from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from apps.workflows import runtime
from apps.workflows.runtime import WorkflowRuntimeError


def _run() -> SimpleNamespace:
    return SimpleNamespace(release=object(), consumer_id=7)


def test_retrieve_node_resolves_explicit_profile_without_release_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    body = {
        "api_version": "agenthub/retrieval/v1",
        "kind": "RetrievalProfile",
        "mode": "keyword",
        "top_k": 4,
        "score_threshold": 0,
    }
    monkeypatch.setattr(runtime, "get_artifact_body_for_role", lambda release, role: body)

    def _retrieve(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"chunks": [], "top_score": 0.0}

    monkeypatch.setattr("apps.orchestration.rag_steps.retrieve_for_release", _retrieve)
    result = runtime._execute_eligible_node(
        node={
            "id": "retrieve-a",
            "type": "retrieve",
            "config": {"retrieval_profile_ref": "retrieve_a"},
        },
        state={"input": {"question": "Soru"}},
        input_env=None,
        run=_run(),
    )

    assert result == {"chunks": [], "top_score": 0.0}
    assert captured["retrieval_profile"] == {
        "mode": "keyword",
        "top_k": 4,
        "score_threshold": 0,
    }


def test_retrieve_node_uses_legacy_fallback_only_when_binding_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "apps.orchestration.rag_steps.retrieve_for_release",
        lambda **kwargs: captured.update(kwargs) or {"chunks": [], "top_score": 0.0},
    )
    runtime._execute_eligible_node(
        node={"id": "retrieve", "type": "retrieve", "config": {}},
        state={"input": {"question": "Soru"}},
        input_env=None,
        run=_run(),
    )
    assert captured["retrieval_profile"] is None

    monkeypatch.setattr(runtime, "get_artifact_body_for_role", lambda release, role: None)
    with pytest.raises(WorkflowRuntimeError) as exc:
        runtime._execute_eligible_node(
            node={
                "id": "retrieve",
                "type": "retrieve",
                "config": {"retrieval_profile_ref": "missing"},
            },
            state={"input": {"question": "Soru"}},
            input_env=None,
            run=_run(),
        )
    assert exc.value.code == "WORKFLOW_RETRIEVAL_BINDING_INVALID"
