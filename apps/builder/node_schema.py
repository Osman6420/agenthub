"""Node-schema generation for the visual builder.

Produces the palette and per-node configuration schema the frontend renders. It exposes
only *public* information: builtin node types, the org's active custom-node refs, and the
org's tool **binding roles** with their approval flag. It deliberately never returns tool
endpoints, destinations, tool-definition manifests, or ``secret:<name>`` values — the UI
must not be able to learn them.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from apps.tools.models import ToolBinding, ToolStatus
from apps.workflows.compiler import (
    AGENT_CALL_ACTIONS,
    MAX_AGENT_CALL_DECISIONS,
    MAX_CHILD_DEPTH,
    MAX_EDGES,
    MAX_FOR_EACH_ITEMS,
    MAX_NODES,
    MAX_PARALLEL_BRANCHES,
    MAX_PARALLEL_CONCURRENCY,
    MAX_PARALLEL_DURATION_SECONDS,
    MAX_PARALLEL_STATE_BYTES,
    MAX_RETRY_ATTEMPTS,
    MAX_RETRY_BACKOFF_SECONDS,
)
from apps.workflows.models import CustomNodeDefinition, CustomNodeStatus
from apps.workflows.state_mapping import (
    ALLOWED_WRITE_ROOTS,
    MAX_MAPPING_ENTRIES,
    MAX_POINTER_LENGTH,
)

# Node types that may carry a node-level ``retry_policy`` (mirrors the compiler's
# retry-ineligible set inverted). Exposed as a UI hint; the compiler stays authoritative.
_RETRY_ELIGIBLE_TYPES = frozenset(
    {"retrieve", "generate", "format_output", "validate_contract", "custom", "transform"}
)

# Field descriptors are data the frontend uses to render inputs. ``kind`` is a UI hint,
# not an authoritative validator — the backend compiler remains the source of truth.
_BUILTIN_NODES: list[dict[str, Any]] = [
    {
        "type": "input",
        "label": "Input",
        "category": "io",
        "singleton": True,
        "is_entry": True,
        "fields": [],
    },
    {
        "type": "retrieve",
        "label": "Retrieve",
        "category": "rag",
        "supports_mapping": True,
        "fields": [],
    },
    {
        "type": "generate",
        "label": "Generate",
        "category": "rag",
        "supports_mapping": True,
        "fields": [
            {
                "name": "prompt_ref",
                "kind": "identifier",
                "required": False,
                "help": ("İsteğe bağlı prompt release rolü; boşsa varsayılan prompt kullanılır."),
            },
            {
                "name": "model_profile_ref",
                "kind": "identifier",
                "required": False,
                "help": ("İsteğe bağlı model profili release rolü; boşsa varsayılan kullanılır."),
            },
        ],
    },
    {
        "type": "format_output",
        "label": "Format output",
        "category": "rag",
        "fields": [
            {
                "name": "template_ref",
                "kind": "text",
                "required": False,
                "help": "Mevcut runtime bunu artifact ref değil, doğrudan çıktı metni sayar.",
            }
        ],
    },
    {
        "type": "validate_contract",
        "label": "Validate contract",
        "category": "governance",
        "fields": [],
    },
    {
        "type": "condition",
        "label": "Condition",
        "category": "control",
        "has_conditional_edges": True,
        "fields": [
            {
                "name": "expression",
                "kind": "expression",
                "required": True,
                "help": "Bounded boolean expression over the run state.",
            }
        ],
    },
    {
        "type": "tool",
        "label": "Tool",
        "category": "tool",
        "supports_mapping": True,
        "fields": [
            {
                "name": "binding_role",
                "kind": "enum",
                "required": True,
                "options_ref": "tool_binding_roles",
                "help": "A tool binding role pinned into the release at compile time.",
            },
            {
                "name": "input_key",
                "kind": "identifier",
                "required": False,
                "help": "Legacy input state key; use input_mapping instead for typed selection.",
            },
            {
                "name": "output_key",
                "kind": "identifier",
                "required": False,
                "help": "Legacy output state key; provide exactly one of output_key/output_mapping",
            },
        ],
    },
    {
        "type": "transform",
        "label": "Transform",
        "category": "governance",
        "supports_mapping": True,
        "fields": [
            {
                "name": "transform_profile_ref",
                "kind": "identifier",
                "required": True,
                "help": (
                    "Release rolü olarak sabitlenmiş governed transform profili; "
                    "input_mapping ve output_mapping zorunludur."
                ),
            }
        ],
    },
    {
        "type": "custom",
        "label": "Custom node",
        "category": "custom",
        "supports_mapping": True,
        "fields": [
            {
                "name": "node_ref",
                "kind": "enum",
                "required": True,
                "options_ref": "custom_nodes",
                "help": "An organization-allowlisted custom node.",
            },
            {"name": "fields", "kind": "object", "required": False},
        ],
    },
    {
        "type": "event_wait",
        "label": "Event wait",
        "category": "control",
        "supports_mapping": True,
        "fields": [
            {"name": "event_role", "kind": "identifier", "required": True},
            {"name": "payload_schema", "kind": "object", "required": True},
            {"name": "timeout_seconds", "kind": "integer", "required": True},
        ],
    },
    {
        "type": "human_task",
        "label": "Human task",
        "category": "control",
        "supports_mapping": True,
        "fields": [
            {"name": "allowed_decision_roles", "kind": "list", "required": True},
            {"name": "decision_schema", "kind": "object", "required": True},
            {"name": "timeout_seconds", "kind": "integer", "required": True},
            {"name": "deny_self_decision", "kind": "boolean", "required": False},
            {"name": "escalation_role", "kind": "identifier", "required": False},
            {"name": "escalation_timeout_seconds", "kind": "integer", "required": False},
        ],
    },
    {
        "type": "timer",
        "label": "Durable timer",
        "category": "control",
        "fields": [{"name": "delay_seconds", "kind": "integer", "required": True}],
    },
    {
        "type": "parallel",
        "label": "Paralel",
        "category": "control",
        "branch_owner": True,
        "fields": [
            {
                "name": "join",
                "kind": "identifier",
                "required": True,
                "help": "Bu paralel bölgeyi kapatan join node id'si.",
            },
            {
                "name": "max_concurrency",
                "kind": "integer",
                "required": True,
                "min": 1,
                "max": MAX_PARALLEL_CONCURRENCY,
                "help": f"Aynı anda çalışacak dal sayısı (1..{MAX_PARALLEL_CONCURRENCY}).",
            },
            {
                "name": "max_duration_seconds",
                "kind": "integer",
                "required": False,
                "min": 1,
                "max": MAX_PARALLEL_DURATION_SECONDS,
                "help": f"Bölge için üst süre sınırı (1..{MAX_PARALLEL_DURATION_SECONDS} sn).",
            },
            {
                "name": "max_state_bytes",
                "kind": "integer",
                "required": False,
                "min": 1,
                "max": MAX_PARALLEL_STATE_BYTES,
                "help": f"Bölge durumu için bayt sınırı (1..{MAX_PARALLEL_STATE_BYTES}).",
            },
        ],
    },
    {
        "type": "for_each",
        "label": "Her biri için",
        "category": "control",
        "branch_owner": True,
        "fields": [
            {
                "name": "items_path",
                "kind": "pointer",
                "required": True,
                "help": "Üzerinde döngü kurulacak liste için JSON Pointer.",
            },
            {
                "name": "item_path",
                "kind": "pointer",
                "required": True,
                "help": "Her yinelemede öğenin yazılacağı JSON Pointer.",
            },
            {
                "name": "max_items",
                "kind": "integer",
                "required": True,
                "min": 1,
                "max": MAX_FOR_EACH_ITEMS,
                "help": f"İşlenecek en fazla öğe sayısı (1..{MAX_FOR_EACH_ITEMS}).",
            },
            {
                "name": "max_concurrency",
                "kind": "integer",
                "required": True,
                "min": 1,
                "max": MAX_PARALLEL_CONCURRENCY,
                "help": f"Aynı anda işlenecek öğe sayısı (1..{MAX_PARALLEL_CONCURRENCY}).",
            },
            {
                "name": "body_entry",
                "kind": "identifier",
                "required": True,
                "help": "Her öğe için çalışacak gövde giriş node id'si.",
            },
            {
                "name": "join",
                "kind": "identifier",
                "required": True,
                "help": "Yinelemeleri kapatan join node id'si.",
            },
        ],
    },
    {
        "type": "join",
        "label": "Birleştir",
        "category": "control",
        "fields": [
            {
                "name": "mode",
                "kind": "enum",
                "required": True,
                "options": ["all", "threshold", "fail_fast"],
                "help": "Dal birleştirme politikası.",
            },
            {
                "name": "branches",
                "kind": "list",
                "required": True,
                "max_items": MAX_PARALLEL_BRANCHES,
                "help": "Birleştirilecek dal etiketleri.",
            },
            {
                "name": "merge",
                "kind": "mapping",
                "required": True,
                "help": "Yalnızca dal çıktılarından (/branches/<dal>/...) okuyan birleştirme.",
            },
            {
                "name": "required",
                "kind": "integer",
                "required": False,
                "min": 1,
                "help": "threshold modunda başarılı olması gereken dal sayısı.",
            },
        ],
    },
    {
        "type": "subworkflow",
        "label": "Alt iş akışı",
        "category": "composition",
        "supports_mapping": True,
        "mapping_required": True,
        "composition": True,
        "supports_retry": True,
        "fields": [
            {
                "name": "workflow_role",
                "kind": "identifier",
                "required": True,
                "help": "Release manifestindeki çocuk iş akışı rolü (artifact id/url değil).",
            },
            {
                "name": "max_depth",
                "kind": "integer",
                "required": True,
                "min": 1,
                "max": MAX_CHILD_DEPTH,
                "help": f"İzin verilen en fazla iç içe derinlik (1..{MAX_CHILD_DEPTH}).",
            },
        ],
    },
    {
        "type": "agent_call",
        "label": "Ajan çağrısı",
        "category": "composition",
        "supports_mapping": True,
        "mapping_required": True,
        "composition": True,
        "supports_retry": True,
        "fields": [
            {
                "name": "agent_role",
                "kind": "identifier",
                "required": True,
                "help": "Release manifestindeki çocuk ajan rolü.",
            },
            {
                "name": "max_decisions",
                "kind": "integer",
                "required": True,
                "min": 1,
                "max": MAX_AGENT_CALL_DECISIONS,
                "help": f"Çocuk ajanın en fazla karar sayısı (1..{MAX_AGENT_CALL_DECISIONS}).",
            },
            {
                "name": "allowed_actions",
                "kind": "list",
                "required": True,
                "options": sorted(AGENT_CALL_ACTIONS),
                "help": "Çocuk ajana devredilen izinli eylemler (üst yetkinin alt kümesi).",
            },
        ],
    },
    {"type": "end", "label": "End", "category": "io", "is_terminal": True, "fields": []},
]

# Stamp node-level retry/compensation affordances (UI hints only; the compiler enforces).
for _node in _BUILTIN_NODES:
    if _node["type"] in _RETRY_ELIGIBLE_TYPES:
        _node["supports_retry"] = True
    if _node["type"] == "tool":
        _node["supports_compensation"] = True

# Node-level retry_policy shape surfaced to the builder (non-authoritative UI hint; the
# backend compiler in apps.workflows.compiler remains the source of truth).
_RETRY_POLICY_SCHEMA: dict[str, Any] = {
    "max_attempts": {"min": 1, "max": MAX_RETRY_ATTEMPTS},
    "backoff_seconds": {"min": 0, "max": MAX_RETRY_BACKOFF_SECONDS},
    "retry_on": ["transient"],
    "idempotent_required": True,
}

# Restricted JSON Pointer mapping metadata surfaced to the builder (non-authoritative UI hint;
# the backend compiler and apps.workflows.state_mapping remain the source of truth).
_MAPPING_SCHEMA: dict[str, Any] = {
    "entry_keys": ["from", "to"],
    "max_entries": MAX_MAPPING_ENTRIES,
    "max_pointer_length": MAX_POINTER_LENGTH,
    "writable_roots": sorted(ALLOWED_WRITE_ROOTS),
}


def build_node_schema(*, organization_id: int) -> dict[str, Any]:
    """Return the builder palette + config schema for one organization.

    Only public governance metadata is included. Tool endpoints/secrets are never
    exposed; only binding *role* names and their approval flag are returned.
    """
    tool_binding_roles = []
    for binding in (
        ToolBinding.objects.filter(organization_id=organization_id, status=ToolStatus.ACTIVE)
        .select_related("tool_definition")
        .order_by("logical_id")
    ):
        description = binding.tool_definition.manifest.get("description", "")
        tool_binding_roles.append(
            {
                "role": binding.logical_id,
                "approval_required": bool(binding.approval_required),
                "description": description[:500] if isinstance(description, str) else "",
                "risk": binding.tool_definition.risk,
                "side_effecting": bool(binding.tool_definition.side_effecting),
            }
        )
    custom_nodes = [
        {"node_ref": logical_id}
        for logical_id in CustomNodeDefinition.objects.filter(
            organization_id=organization_id, status=CustomNodeStatus.ACTIVE
        )
        .order_by("logical_id")
        .values_list("logical_id", flat=True)
        .distinct()
    ]
    # Composition (subworkflow/agent_call) is deployment-gated. It is always shown in the
    # palette so authors can see it, but marked ``gated`` when disabled so the UI can render
    # it as unavailable; the compiler independently rejects composition nodes when the gate is
    # off, so UI exposure can never activate a gated capability.
    composition_enabled = bool(getattr(settings, "WORKFLOW_COMPOSITION_ENABLED", False))
    return {
        "dsl": {"api_version": "agenthub/v1", "kind": "Workflow"},
        "limits": {
            "max_nodes": MAX_NODES,
            "max_edges": MAX_EDGES,
            "max_parallel_branches": MAX_PARALLEL_BRANCHES,
        },
        "node_types": _BUILTIN_NODES,
        "mapping": _MAPPING_SCHEMA,
        "retry_policy": _RETRY_POLICY_SCHEMA,
        "gates": {"composition_enabled": composition_enabled},
        "tool_binding_roles": tool_binding_roles,
        "custom_nodes": custom_nodes,
    }
