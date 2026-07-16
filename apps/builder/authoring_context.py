"""Bounded, tenant-scoped public context for Studio AI authoring."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.conf import settings

from apps.builder.models import WorkflowDraft
from apps.builder.node_schema import build_node_schema
from apps.catalog.models import AIProject, Scenario

CONTEXT_CONTRACT = "agenthub.studio-authoring-context/v1"
MAX_CONTEXT_BYTES = 64 * 1024
MAX_CATALOG_ENTRIES = 100


def _bounded(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return items[: int(getattr(settings, "AI_AUTHORING_MAX_CATALOG_ENTRIES", MAX_CATALOG_ENTRIES))]


def build_authoring_context(*, project: AIProject, scenario: Scenario) -> dict[str, Any]:
    """Return deterministic safe metadata; callers must authorize lineage first."""
    if scenario.organization_id != project.organization_id or scenario.project_id != project.id:
        raise ValueError("scenario_project_mismatch")
    schema = build_node_schema(organization_id=project.organization_id)
    snapshot: dict[str, Any] = {
        "contract": CONTEXT_CONTRACT,
        "organization": {"slug": project.organization.slug, "name": project.organization.name},
        "project": {
            "slug": project.slug,
            "name": project.name,
            "risk_level": project.risk_level,
            "default_locale": project.default_locale,
        },
        "scenario": {
            "slug": scenario.slug,
            "name": scenario.name,
            "type": scenario.type,
            "risk_level": scenario.risk_level,
            "status": scenario.status,
        },
        "workflow": {
            "dsl": schema["dsl"],
            "limits": schema["limits"],
            "node_types": schema["node_types"],
            "tool_binding_roles": _bounded(schema["tool_binding_roles"]),
            "custom_nodes": _bounded(schema["custom_nodes"]),
        },
        "drafts": [
            {"id": pk, "name": name, "revision": revision}
            for pk, name, revision in WorkflowDraft.objects.filter(
                organization_id=project.organization_id,
                project=project,
                scenario=scenario,
            )
            .order_by("id")
            .values_list("id", "name", "revision")[:MAX_CATALOG_ENTRIES]
        ],
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    limit = int(getattr(settings, "AI_AUTHORING_MAX_CONTEXT_BYTES", MAX_CONTEXT_BYTES))
    size = len(canonical.encode("utf-8"))
    if size > limit:
        raise ValueError("authoring_context_too_large")
    return {
        "snapshot": snapshot,
        "checksum": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "bytes": size,
        "token_estimate": (size + 3) // 4,
    }


def validate_workflow_references(body: dict[str, Any], context: dict[str, Any]) -> None:
    """Fail closed when model output names a capability outside its exact snapshot."""
    workflow = context["snapshot"]["workflow"]
    tool_roles = {item["role"] for item in workflow["tool_binding_roles"]}
    custom_refs = {item["node_ref"] for item in workflow["custom_nodes"]}
    for node in body.get("spec", {}).get("nodes", []):
        config = node.get("config") or {}
        if node.get("type") == "tool" and config.get("binding_role") not in tool_roles:
            raise ValueError("capability_reference_invalid")
        if node.get("type") == "custom" and config.get("node_ref") not in custom_refs:
            raise ValueError("capability_reference_invalid")
        if node.get("type") == "generate" and (
            config.get("prompt_ref") or config.get("model_profile_ref")
        ):
            # Release roles are not currently available in the Studio context. An empty
            # ref uses the governed runtime defaults; a named/invented role fails closed.
            raise ValueError("capability_reference_invalid")
