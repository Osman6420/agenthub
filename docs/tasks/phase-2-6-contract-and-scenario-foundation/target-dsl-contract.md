# P2.6.0 Target Workflow DSL Contract

This is the accepted implementation target for the in-place unreleased `agenthub/v1` workflow
evolution. The inert wrappers in `fixtures/workflows/*.target.json` illustrate it. Current runtime
support remains defined by code until each owning part is implemented and verified.

## Envelope and compatibility

- Source remains `api_version=agenthub/v1`, `kind=Workflow` with exact `metadata` and `spec` keys.
- The compiled form retains a separate compiler/transition contract version. Old compiled graphs or
  resumable records cannot run under a mismatched version.
- Existing node behavior remains unless explicitly revised by its owning part. Existing dummy
  fixtures/releases move atomically at the approved non-production cutover; there is no dual v1/v2
  runtime.
- Target wrappers contain `fixture_status=target_not_importable`, so they are never direct artifact
  bodies. Removing the wrapper before implementation does not make them supported.

## Common node shape

Nodes keep `id`, `type` and optional exact `config`. Data-consuming/producing nodes may additionally
declare:

```json
{
  "input_mapping": [{"from": "/input/case_id", "to": "/input/case_id"}],
  "output_mapping": [{"from": "/output", "to": "/branches/policy/output"}],
  "retry": {"mode": "idempotent_transient_only", "max_attempts": 2}
}
```

- `from` and `to` are restricted absolute JSON Pointers defined by ADR-0010.
- Mapping destination conflicts and protected namespace writes are compiler errors.
- `retry` is absent by default. It cannot make a non-idempotent or `outcome_unknown` action retryable.
- Compensation is a separately pinned compiled relationship owned by P2.6.4; model/runtime state
  cannot invent it.

## Edge shape

Edges retain `from` and `to` and admit only one routing discriminator:

- `when: true|false` for existing condition branches;
- `branch: <compiled branch name>` within a parallel/collection region;
- `on: <closed outcome code>` for success/failure/wait/decision recovery routing.

An edge with multiple discriminators, an unknown outcome or a route invalid for its source node is
rejected. Initial outcome vocabulary is `success`, `failure`, `timeout`, `cancelled`,
`outcome_unknown`, `budget_exhausted`, `approved`, `rejected` and `expired`. Owning parts may reduce
which outcomes a specific node accepts but cannot accept arbitrary strings.

## New primitive contracts

### `parallel`

`config` contains exact `join` and `max_concurrency`. Outgoing `branch` edges define a unique closed
branch set. Every branch has one compiled path to the declared join; nested ownership is explicit.

### `join`

`config` contains exact `mode`, ordered `branches`, explicit `merge`, and `required` only for
`threshold`. Modes are `all`, `threshold`, `fail_fast`. Branch results live under
`/branches/<name>/...`; only merge mappings produce shared downstream state.

### `for_each`

`config` contains exact `items_path`, `item_path`, `max_items`, `max_concurrency`, `body_entry` and
`join`. Each item uses a stable server-assigned ordinal/key and independent result namespace.
Iteration order and join output are deterministic; dynamic graph mutation is forbidden.

### `human_task`

`config` contains exact `decision_roles`, `self_approval_allowed`, `expires_in_seconds` and
`decision_schema`. The runtime creates a typed durable task bound to the run/release/request checksum.
Decision, timeout and expiry follow explicit `on` routes.

### `wait_event`

`config` contains an active server-owned event role, payload schema reference and bounded expiry.
Endpoints, credentials and public correlation tokens are never stored in DSL. Runtime issues the
one-time opaque correlation after authorization.

### `wait_timer`

`config` contains a bounded duration/deadline policy. It persists a deadline and releases the worker;
sleeping Celery workers are forbidden.

### `subworkflow` and `agent_call`

`config` names a release-manifest role, never an artifact ID, URL or latest version. `subworkflow`
declares bounded depth; `agent_call` declares bounded decisions and a closed action subset. ADR-0009
defines effective capability attenuation. Both require input/output mappings.

### `transform`

Uses a pinned transform profile or the closed operation registry selected by P2.6.1. It cannot carry
code, general expressions or templates.

### `custom`

Existing managed-node references remain compatible. Approved tenant-authored Python nodes use the
same opaque reference position only after P2.6.8 resolves an exact active revision/checksum into the
release. Source is never present in workflow JSON.

## Server-owned state namespaces

Implementation may expose safe business namespaces such as `/input`, `/retrieval`, `/branches`,
`/evidence`, `/decisions` and `/output`. The compiler/runtime deny mappings to server-owned tenant,
actor, authorization, capability, release/manifest, execution-context, secret, orchestration-control,
budget and audit namespaces regardless of spelling/case aliases.

## Stable diagnostics target

At minimum the compiler/authoring API must provide safe stable codes with JSON Pointer locations:

| Code | Meaning |
| --- | --- |
| `WORKFLOW_PATH_INVALID` | Pointer syntax or root is forbidden |
| `WORKFLOW_PATH_PROTECTED` | Mapping writes a server-owned namespace |
| `WORKFLOW_MAPPING_TYPE_MISMATCH` | Known source/target schemas are incompatible |
| `WORKFLOW_MAPPING_CONFLICT` | Two results target the same unowned location |
| `WORKFLOW_PARALLEL_REGION_INVALID` | Branch ownership/join path is incomplete or ambiguous |
| `WORKFLOW_JOIN_POLICY_INVALID` | Mode, threshold, branch set or merge is invalid |
| `WORKFLOW_WAIT_POLICY_INVALID` | Event/timer/human-task policy is unbounded or malformed |
| `WORKFLOW_ROUTE_INVALID` | Edge discriminator/outcome is invalid for the source |
| `WORKFLOW_CHILD_AUTHORITY_INVALID` | Child role/envelope/depth violates the compiled authority contract |
| `WORKFLOW_RETRY_UNSAFE` | Retry requested for an ineligible or ambiguous operation |
| `WORKFLOW_BUDGET_EXCEEDED` | Static graph/state/fan-out/depth/call bound is exceeded |

Messages remain content-free and do not expose schemas from another tenant, endpoints, credentials,
source code or raw provider errors.

## Owning implementation parts

- P2.6.1: paths, mappings and transforms
- P2.6.2: parallel, join and `for_each`
- P2.6.3: human/event/timer waits
- P2.6.4: outcome routes, retry and compensation
- P2.6.5: child workflow/agent calls
- P2.6.6: governed agent decision loop
- P2.6.8: exact approved Python-node resolution
- P2.6.11: Studio diagnostics, eval and operations closure
