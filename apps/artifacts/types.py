"""Artifact types (v3 plan §6.3).

Each type is an immutable, versioned definition that a release can pin.
"""

from __future__ import annotations

from django.db import models


class ArtifactType(models.TextChoices):
    INPUT_CONTRACT = "input_contract", "Input contract"
    OUTPUT_CONTRACT = "output_contract", "Output contract"
    PROMPT_TEMPLATE = "prompt_template", "Prompt template"
    POLICY_PROFILE = "policy_profile", "Policy profile"
    MODEL_PROFILE = "model_profile", "Model profile"
    SOURCE_DEFINITION = "source_definition", "Source definition"
    CHUNKING_PROFILE = "chunking_profile", "Chunking profile"
    RETRIEVAL_PROFILE = "retrieval_profile", "Retrieval profile"
    WORKFLOW_DEFINITION = "workflow_definition", "Workflow definition"
    CUSTOM_NODE_DEFINITION = "custom_node_definition", "Custom node definition"
    TOOL_DEFINITION = "tool_definition", "Tool definition"
    TOOL_BINDING = "tool_binding", "Tool binding"
    AGENT_DEFINITION = "agent_definition", "Agent definition"
    MEMORY_POLICY = "memory_policy", "Memory policy"
    EVAL_SUITE = "eval_suite", "Eval suite"


# Types whose body must itself be a valid JSON Schema document.
JSON_SCHEMA_TYPES: frozenset[str] = frozenset(
    {ArtifactType.INPUT_CONTRACT, ArtifactType.OUTPUT_CONTRACT}
)
