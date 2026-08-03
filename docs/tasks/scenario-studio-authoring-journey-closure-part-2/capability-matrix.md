# Part 2 Artifact Capability Matrix

| Artifact/profile | Canonical validator | Current consumer | Part 2 authoring capability |
| --- | --- | --- | --- |
| `chunking_profile` | `validate_chunking_profile` (`agenthub/chunking/v1`) | ingestion staged build | Part 2A structured create/new-version |
| `retrieval_profile` | `validate_retrieval_profile` (`agenthub/retrieval/v1`) | retrieval/orchestration/evaluation | Part 2A structured create/new-version |
| `prompt_template` | prompt template validator | runtime/summary contract | Existing structured create/new-version |
| `model_profile` artifact | UUID-only model reference validator | orchestration resolver | Part 2B closed platform-profile selection |
| embedding profile revision | platform registry/service validation | ingestion/vector index | Part 2B safe read + platform handoff |
| OCR profile revision | platform registry/service validation | document extraction | Part 2B safe read + platform handoff |
| remaining registry artifacts | per-type validator where present | type-specific | Later structured, validated JSON, or explicit read-only state |

The browser is never the validation authority. Part 2 forms construct only documented fields and
publication always re-runs `apps.artifacts.validation.validate_body` through the immutable artifact
service.
