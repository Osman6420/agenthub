"""RAG runtime: release/context gating, grounding fallback, output governance."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache

from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioType
from apps.orchestration.runtime import RuntimeReleaseError, run_rag
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.releases.models import ScenarioRelease
from apps.retrieval.providers import StaticRetrievalProvider
from apps.retrieval.types import RetrievedChunk
from apps.tenancy.models import Organization

OUTPUT_CONTRACT = {
    "type": "object",
    "required": ["answer", "sources"],
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string", "maxLength": 4000},
        "sources": {"type": "array"},
        "fallback_used": {"type": "boolean"},
    },
}
STRICT_OUTPUT_CONTRACT = {
    "type": "object",
    "required": ["answer", "sources", "must_have"],
    "properties": {"answer": {"type": "string"}, "sources": {"type": "array"}},
}


@pytest.fixture(autouse=True)
def _clear_cache() -> Any:
    cache.clear()
    yield
    cache.clear()


def _build_release(
    *, policy: dict | None = None, output_contract: dict | None = None, active: bool = True
) -> ScenarioRelease:
    org = Organization.objects.create(slug="mcm", name="MCM")
    project = AIProject.objects.create(organization=org, slug="cx", name="CX")
    scenario = Scenario.objects.create(
        project=project,
        slug="info",
        name="Info",
        type=ScenarioType.RAG,
        status=LifecycleStatus.ACTIVE,
    )
    refs = []
    create_artifact_version(
        organization=org,
        artifact_type=ArtifactType.PROMPT_TEMPLATE,
        logical_id="p",
        body={"template": "Answer using context."},
        created_by="t",
    )
    refs.append(ArtifactRef("prompt", ArtifactType.PROMPT_TEMPLATE, "p", 1))
    if policy is not None:
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.POLICY_PROFILE,
            logical_id="pol",
            body=policy,
            created_by="t",
        )
        refs.append(ArtifactRef("policy", ArtifactType.POLICY_PROFILE, "pol", 1))
    if output_contract is not None:
        create_artifact_version(
            organization=org,
            artifact_type=ArtifactType.OUTPUT_CONTRACT,
            logical_id="oc",
            body=output_contract,
            created_by="t",
        )
        refs.append(ArtifactRef("output_contract", ArtifactType.OUTPUT_CONTRACT, "oc", 1))

    release = compile_release(
        scenario=scenario, refs=refs, runtime_version="rt:3.0.0", created_by="t"
    )
    if active:
        promote_release(release)
    return release


def _ctx() -> dict:
    return {"organization_id": 1, "request_id": "req"}  # runtime does not re-verify signature


@pytest.mark.django_db
def test_inactive_release_is_rejected() -> None:
    release = _build_release(active=False)  # candidate
    with pytest.raises(RuntimeReleaseError):
        run_rag(execution_context=_ctx(), validated_input={"query": "x"}, release=release)


@pytest.mark.django_db
def test_grounding_fallback_when_no_context() -> None:
    release = _build_release(policy={"grounding": {"required": True, "min_top_score": 0.45}})
    result = run_rag(
        execution_context=_ctx(),
        validated_input={"query": "x"},
        release=release,
        retrieval_provider=StaticRetrievalProvider([]),  # nothing retrieved
    )
    assert result.fallback_used is True
    assert result.output["fallback_used"] is True
    assert result.output["sources"] == []


@pytest.mark.django_db
def test_grounding_fallback_below_threshold() -> None:
    release = _build_release(policy={"grounding": {"required": True, "min_top_score": 0.45}})
    low = RetrievedChunk(text="weak", source_id="s1", source_uri="u1", score=0.1)
    result = run_rag(
        execution_context=_ctx(),
        validated_input={"query": "x"},
        release=release,
        retrieval_provider=StaticRetrievalProvider([low]),
    )
    assert result.fallback_used is True


@pytest.mark.django_db
def test_grounded_completed_with_runtime_citations() -> None:
    release = _build_release(
        policy={"grounding": {"required": True, "min_top_score": 0.45}},
        output_contract=OUTPUT_CONTRACT,
    )
    chunk = RetrievedChunk(
        text="Iade 14 gun icinde yapilir.",
        source_id="mcm",
        source_uri="https://x/iade",
        title="Iade",
        score=0.9,
    )
    result = run_rag(
        execution_context=_ctx(),
        validated_input={"query": "iade"},
        release=release,
        retrieval_provider=StaticRetrievalProvider([chunk]),
    )
    assert result.status == "completed"
    assert result.fallback_used is False
    assert result.output["answer"] == "Iade 14 gun icinde yapilir."
    assert result.output["sources"][0]["source_id"] == "mcm"
    assert result.output["sources"][0]["source_uri"] == "https://x/iade"


@pytest.mark.django_db
def test_output_contract_violation_returns_fallback_not_model_output() -> None:
    release = _build_release(output_contract=STRICT_OUTPUT_CONTRACT)
    leaked = RetrievedChunk(text="LEAKED-SECRET-ANSWER", source_id="s", source_uri="u", score=0.9)
    result = run_rag(
        execution_context=_ctx(),
        validated_input={"query": "x"},
        release=release,
        retrieval_provider=StaticRetrievalProvider([leaked]),
    )
    # Model output failed the contract -> server-controlled fallback, no leak.
    assert result.fallback_used is True
    assert "LEAKED-SECRET-ANSWER" not in result.output["answer"]


@pytest.mark.django_db
def test_citations_required_fallback_when_no_sources() -> None:
    release = _build_release(policy={"output": {"citations": "required"}})
    result = run_rag(
        execution_context=_ctx(),
        validated_input={"query": "x"},
        release=release,
        retrieval_provider=StaticRetrievalProvider([]),  # no sources
    )
    assert result.fallback_used is True
