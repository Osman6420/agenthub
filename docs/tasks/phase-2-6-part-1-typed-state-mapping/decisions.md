# P2.6.1 Closed Implementation Decisions

These close the plan's open questions from live compiler/runtime/release/builder code before
implementation. They stay within the P2.6.0 owner decisions and ADR-0008/ADR-0010; they do not add
authentication/authorization, a public API surface, a production dependency or a database reset.

## D1 — Transform node contract: pinned profile only

The workflow `transform` node references an existing immutable `transform_profile` artifact through a
release **manifest role**, exactly like `generate`'s `prompt_ref`/`model_profile_ref`:

```json
{"id": "normalize", "type": "transform",
 "config": {"transform_profile_ref": "transform_profile.normalize"},
 "input_mapping": [{"from": "/input/rows", "to": "/items"}],
 "output_mapping": [{"from": "/result", "to": "/evidence/normalized"}]}
```

No inline operation list, expression or template is accepted. The node reuses the closed
`agenthub/transform/v1` registry and `apps.artifacts.governed_dsl.execute_transform` unchanged. Because
it only reuses the existing artifact type, release manifest pinning and governed executor, it does not
create a new durable architecture boundary and needs no new ADR (ADR-0010 already sanctions a "pinned
transform profile"). The release compiler fails closed if a transform node's role is not pinned to a
`transform_profile` in the same release, so a run can never select an unpinned/foreign/mutable profile.

## D2 — Fixed resource limits (constants, not configuration)

In `apps/workflows/state_mapping.py`:

- `MAX_POINTER_LENGTH = 256` characters per JSON Pointer.
- `MAX_POINTER_SEGMENTS = 12` decoded segments (depth bound).
- `MAX_MAPPING_ENTRIES = 24` entries per `input_mapping` and per `output_mapping`.

Total workflow-state bytes remain bounded by the existing `MAX_STATE_BYTES = 1_048_576`, re-enforced by
`_assert_state_size` after every mapping application (per-value expansion is bounded transitively).

## D3 — Optional, additive mappings; strict node-local isolation when present

`input_mapping`/`output_mapping` are optional on the eligible node types
(`retrieve`, `generate`, `tool`, `custom`, `transform`).

- **Absent** → exact current ("ambient") behavior is preserved, so existing disposable source fixtures
  still compile. This is the compatibility default.
- **`input_mapping` present** → the node consumes only a **node-local input envelope** built from a
  snapshot of pre-node state; it does not receive ambient state it did not declare. For `tool` and
  `custom` (the exfiltration-capable nodes) this is a hard isolation boundary.
- **`output_mapping` present** → the node's canonical output envelope is projected into declared
  business-state destinations under the protected-namespace and conflict rules, replacing the legacy
  default write. Application is **copy-on-success**: state is mutated only if every entry resolves and
  type-checks, so a failed mapping never partially mutates run state.

`transform` always requires both mappings (it has no ambient default input/output). `tool` requires an
output sink (`output_mapping` XOR `output_key`) and at most one input source (`input_mapping` XOR
`input_key`); the other eligible nodes keep their existing default input source and output target when a
mapping is absent.

## D4 — Compiled workflow contract version bump (atomic cutover, no migration)

The compiled graph `api_version` becomes `agenthub/compiled-workflow/v2` and the service sets
`compiler_version = "workflow-compiler/v2"`. The runtime fails closed
(`WORKFLOW_COMPILER_VERSION_UNSUPPORTED`) on any other compiled `api_version`, so a stale v1 compiled
graph or checkpoint can never be resumed under the new mapping semantics. Because `compiler_version` is
set explicitly by the service (the model default is an unused fallback) and the compiled graph lives in
an existing `JSONField`, **no database migration is required**; this is a compatibility/contract cutover,
not a schema change. The uniqueness key `(scenario, source_artifact, compiler_version)` means v2
compiles never collide with any residual v1 row.

## D5 — Protected namespace policy: deny-by-default allowlist on the canonical destination root

Mapping **destinations** (`output_mapping.to`) may only write these business roots:
`input`, `retrieval`, `branches`, `evidence`, `decisions`, `output`. The root segment is decoded
(`~0`/`~1`) and NFKC-casefold normalized before the check, and an explicit protected registry
(`tenant`, `actor`, `authorization`, `capability`, `release`, `manifest`, `execution`/`context`,
`secret`, `orchestration`/`control`, `budget`, `audit`, `approval`, …) yields
`WORKFLOW_PATH_PROTECTED`. Any root that is not exactly a canonical business root is denied by default
(also `WORKFLOW_PATH_PROTECTED`), so case, `~`-escape, fullwidth and confusable spellings of a protected
name cannot land in the writable set. `input_mapping.to` addresses only the transient node-local
envelope and is namespace-unrestricted but still parsed and conflict-checked.

## D6 — Schema type checking scope

Cross-node source/destination JSON-Schema inference over the full graph is not attempted at compile time
(open question 5): the compiled graph does not carry a proven per-location state schema. Compile time
enforces pointer syntax, protected roots, entry bounds and destination conflicts; **runtime**
additionally enforces that every `from` path resolves (`WORKFLOW_MAPPING_MISSING`) and that a
destination parent is an object before writing (`WORKFLOW_MAPPING_TYPE_MISMATCH`), before any commit.
This is the "reject-unknown-at-runtime-before-side-effect" case the plan allows.
