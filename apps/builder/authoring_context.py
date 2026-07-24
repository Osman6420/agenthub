"""Bounded, tenant-scoped public context for Studio AI authoring."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.types import ArtifactType
from apps.builder.models import WorkflowDraft
from apps.builder.node_schema import build_node_schema
from apps.catalog.models import AIProject, Scenario
from apps.documents.models import DocumentSetVersionStatus
from apps.releases.models import ReleaseStatus, ScenarioRelease

CONTEXT_CONTRACT = "agenthub.studio-authoring-context/v1"
MAX_CONTEXT_BYTES = 64 * 1024
MAX_CATALOG_ENTRIES = 100
MAX_SCHEMA_DEPTH = 16
MAX_SCHEMA_PROPERTIES = 200
PYTHON_NODE_PUBLIC_FIELDS = (
    "node_ref",
    "execution_class",
    "display_name",
    "purpose",
    "revision",
    "checksum",
    "config_schema",
    "input_schema",
    "output_schema",
)


def _bounded(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return items[: int(getattr(settings, "AI_AUTHORING_MAX_CATALOG_ENTRIES", MAX_CATALOG_ENTRIES))]


def _python_nodes(organization_id: int) -> list[dict[str, Any]]:
    provider_path = str(getattr(settings, "PYTHON_NODE_PUBLIC_CATALOG_PROVIDER", "")).strip()
    if not provider_path:
        return []
    provider = import_string(provider_path)
    raw = provider(organization_id=organization_id)
    if not isinstance(raw, list):
        raise ValueError("python_node_catalog_invalid")
    safe: list[dict[str, Any]] = []
    for item in raw[: MAX_CATALOG_ENTRIES + 1]:
        if not isinstance(item, dict) or set(item) != set(PYTHON_NODE_PUBLIC_FIELDS):
            raise ValueError("python_node_catalog_invalid")
        if item["execution_class"] != "python":
            raise ValueError("python_node_catalog_invalid")
        if not isinstance(item["node_ref"], str) or not 1 <= len(item["node_ref"]) <= 128:
            raise ValueError("python_node_catalog_invalid")
        if not isinstance(item["revision"], int) or item["revision"] < 1:
            raise ValueError("python_node_catalog_invalid")
        if not isinstance(item["checksum"], str) or len(item["checksum"]) != 64:
            raise ValueError("python_node_catalog_invalid")
        entry = {key: item[key] for key in PYTHON_NODE_PUBLIC_FIELDS}
        for key in ("display_name", "purpose"):
            if not isinstance(entry[key], str) or len(entry[key]) > 500:
                raise ValueError("python_node_catalog_invalid")
        for key in ("config_schema", "input_schema", "output_schema"):
            entry[key] = _safe_schema(entry[key])
        safe.append(entry)
    return _bounded(sorted(safe, key=lambda item: item["node_ref"]))


def _safe_schema(value: Any, *, depth: int = 0, properties: list[int] | None = None) -> Any:
    if depth > MAX_SCHEMA_DEPTH:
        raise ValueError("authoring_schema_too_deep")
    properties = properties if properties is not None else [0]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key in sorted(value):
            if not isinstance(key, str) or len(key) > 128:
                raise ValueError("authoring_schema_invalid")
            properties[0] += 1
            if properties[0] > MAX_SCHEMA_PROPERTIES:
                raise ValueError("authoring_schema_too_large")
            output[key] = _safe_schema(value[key], depth=depth + 1, properties=properties)
        return output
    if isinstance(value, list):
        return [_safe_schema(item, depth=depth + 1, properties=properties) for item in value[:100]]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("authoring_schema_invalid")


def _release_capabilities(scenario: Scenario) -> dict[str, Any]:
    releases = list(
        ScenarioRelease.objects.filter(
            organization_id=scenario.organization_id,
            scenario=scenario,
            status__in=[ReleaseStatus.ACTIVE, ReleaseStatus.CANDIDATE],
        ).order_by("status", "-created_at")[:MAX_CATALOG_ENTRIES]
    )
    roles: dict[str, list[dict[str, str]]] = {
        "prompt_roles": [],
        "model_roles": [],
        "retrieval_roles": [],
    }
    contracts: dict[str, Any] = {"input": None, "output": None}
    seen: set[tuple[str, str]] = set()
    for release in releases:
        artifacts = release.manifest.get("artifacts", {})
        if not isinstance(artifacts, dict):
            continue
        for role, pin in sorted(artifacts.items()):
            if not isinstance(role, str) or not isinstance(pin, dict):
                continue
            artifact_type = pin.get("type")
            ref = pin.get("ref")
            if not isinstance(artifact_type, str) or not isinstance(ref, str):
                continue
            key = (role, ref)
            if key in seen:
                continue
            seen.add(key)
            item = {"role": role, "ref": ref, "release_status": release.status}
            if artifact_type == ArtifactType.PROMPT_TEMPLATE:
                roles["prompt_roles"].append(item)
            elif artifact_type == ArtifactType.MODEL_PROFILE:
                roles["model_roles"].append(item)
            elif artifact_type == ArtifactType.RETRIEVAL_PROFILE:
                roles["retrieval_roles"].append(item)
            elif artifact_type in {ArtifactType.INPUT_CONTRACT, ArtifactType.OUTPUT_CONTRACT}:
                logical_id, separator, version_text = ref.rpartition(":v")
                if not separator or not version_text.isdigit():
                    continue
                artifact = ArtifactVersion.objects.filter(
                    organization_id=scenario.organization_id,
                    type=artifact_type,
                    logical_id=logical_id,
                    version=int(version_text),
                ).first()
                if artifact is not None:
                    contracts[
                        "input" if artifact_type == ArtifactType.INPUT_CONTRACT else "output"
                    ] = {
                        "role": role,
                        "ref": ref,
                        "schema": _safe_schema(artifact.body),
                    }
    return {
        **{key: _bounded(value) for key, value in roles.items()},
        "contracts": contracts,
        "release_lifecycle": [
            {"status": release.status, "checksum": release.artifact_manifest_sha256}
            for release in releases
        ],
    }


def _retrieval_capabilities(scenario: Scenario) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    bindings = scenario.document_set_bindings.select_related("document_set").order_by(
        "document_set__logical_id"
    )
    for binding in bindings[:MAX_CATALOG_ENTRIES]:
        active = binding.document_set.versions.filter(
            organization_id=scenario.organization_id,
            status=DocumentSetVersionStatus.ACTIVE,
            built_index_version__isnull=False,
        ).exists()
        entries.append(
            {
                "logical_id": binding.document_set.logical_id,
                "name": binding.document_set.name,
                "retrieval_available": active,
            }
        )
    return entries


def build_authoring_context(*, project: AIProject, scenario: Scenario) -> dict[str, Any]:
    """Return deterministic safe metadata; callers must authorize lineage first."""
    if scenario.organization_id != project.organization_id or scenario.project_id != project.id:
        raise ValueError("scenario_project_mismatch")
    schema = build_node_schema(organization_id=project.organization_id)
    python_nodes = _python_nodes(project.organization_id)
    release_capabilities = _release_capabilities(scenario)
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
            "gates": schema["gates"],
            "node_types": schema["node_types"],
            "tool_binding_roles": _bounded(schema["tool_binding_roles"]),
            "custom_nodes": _bounded(schema["custom_nodes"]),
            "python_nodes": python_nodes,
        },
        "roles": {
            "prompt": release_capabilities["prompt_roles"],
            "model": release_capabilities["model_roles"],
            "retrieval": release_capabilities["retrieval_roles"],
        },
        "contracts": release_capabilities["contracts"],
        "retrieval": {"document_sets": _retrieval_capabilities(scenario)},
        "releases": release_capabilities["release_lifecycle"],
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
    custom_refs = {item["node_ref"] for item in workflow["custom_nodes"]} | {
        item["node_ref"] for item in workflow["python_nodes"]
    }
    prompt_roles = {item["role"] for item in context["snapshot"]["roles"]["prompt"]}
    model_roles = {item["role"] for item in context["snapshot"]["roles"]["model"]}
    for node in body.get("spec", {}).get("nodes", []):
        config = node.get("config") or {}
        if node.get("type") == "tool" and config.get("binding_role") not in tool_roles:
            raise ValueError("capability_reference_invalid")
        if node.get("type") == "custom" and config.get("node_ref") not in custom_refs:
            raise ValueError("capability_reference_invalid")
        prompt_ref = config.get("prompt_ref")
        if node.get("type") == "generate" and prompt_ref and prompt_ref not in prompt_roles:
            raise ValueError("capability_reference_invalid")
        model_ref = config.get("model_profile_ref")
        if node.get("type") == "generate" and model_ref and model_ref not in model_roles:
            raise ValueError("capability_reference_invalid")
