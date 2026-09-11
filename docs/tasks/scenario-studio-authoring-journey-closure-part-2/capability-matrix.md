# Part 2 Artifact Capability Matrix

| Artifact/profile | Canonical validator | Current consumer | Part 2 authoring capability |
| --- | --- | --- | --- |
| `chunking_profile` | `validate_chunking_profile` (`agenthub/chunking/v1`) | ingestion staged build | Part 2A structured create/new-version |
| `retrieval_profile` | `validate_retrieval_profile` (`agenthub/retrieval/v1`) | retrieval/orchestration/evaluation | Part 2A structured create/new-version |
| `prompt_template` | prompt template validator | runtime/summary contract | Existing structured create/new-version |
| `model_profile` artifact | UUID-only model reference validator | orchestration resolver | Part 2C closed active platform-profile selection/new-version |
| embedding profile revision | platform registry/service validation | ingestion/vector index | Part 2B safe read + platform handoff |
| OCR profile revision | platform registry/service validation | document extraction | Part 2B safe read + platform handoff |
| `workflow_definition` | workflow compiler | runtime | Guided in Workflow graph editor |
| `input_contract`, `output_contract` | JSON Schema validator | request/response boundary | Guided in scenario governed-release inputs |
| `eval_suite` | eval-suite validator | evaluation | Guided in scenario Eval suite form |
| `policy_profile`, `source_definition`, `transform_profile`, `custom_node_definition`, `tool_definition`, `tool_binding`, `memory_policy` | per-type canonical validator | type-specific | Explicit read-only/unsupported state; exact content remains inspectable |

The browser is never the validation authority. Part 2 forms construct only documented fields and
publication always re-runs `apps.artifacts.validation.validate_body` through the immutable artifact
service.

`retrieval_profile.metadata_filter` is preserved when an existing version is copied, but this slice
does not expose a free-form filter editor. That field remains explicitly read-only until a bounded,
typed filter builder is approved; it is not silently discarded.
