from __future__ import annotations

from apps.console.views import _workflow_dsl_guide
from apps.orchestration.authoring import WORKFLOW_SYSTEM_INSTRUCTIONS
from apps.orchestration.authoring_guide import workflow_authoring_guide


def test_workflow_guide_is_shared_by_prompt_and_console_copy_surfaces() -> None:
    guide = workflow_authoring_guide()
    assert guide == WORKFLOW_SYSTEM_INSTRUCTIONS
    assert guide == _workflow_dsl_guide()


def test_workflow_guide_is_concise_and_contains_the_current_contract() -> None:
    guide = workflow_authoring_guide()
    assert guide.startswith("# AgentHub Workflow DSL — LLM Authoring Guide")
    assert "## Node types and exact config" in guide
    assert "support-rag.v1" in guide
    assert "Phase 2.5 transform DSL hedefi" not in guide
    assert len(guide.encode("utf-8")) <= 12_000
