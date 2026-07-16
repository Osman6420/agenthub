# Threat Model: phase-2-6-part-1-typed-state-mapping

## Assets

- Tenant-scoped workflow input, intermediate state, node results and final output
- Server-owned tenant, actor, consumer, scenario, release and capability context
- Tool credentials/references, approval state, retrieval ACLs and immutable release pins
- Compiled workflow/checkpoint integrity and audit lineage
- Availability of web/runtime workers, broker and database

## Actors

- Authorized and malicious scenario authors
- Authorized consumers invoking a released scenario
- Organization/platform operators and auditors
- Runtime workers and deterministic/real providers
- Untrusted model, tool, retrieval, custom-node and future child/event outputs
- A compromised tenant account attempting cross-tenant access or privilege escalation

## Entry points

- Workflow draft, diagnostics, GitOps import, artifact publish and release compilation
- `input_mapping`, `output_mapping`, state pointers and transform configuration
- Consumer workflow input and persisted prior-node state
- Tool/retrieval/model/custom-node output returned to runtime
- Celery redelivery, stale tasks and compiled checkpoint resume
- Builder node-schema and diagnostic responses

## Trust boundaries

- Browser/import/model-authored JSON to canonical server validation
- Source artifact to immutable compiled release/checksum
- Compiled mapping to runtime state transition
- Server-owned execution context to author-writable business state
- Workflow state to tool/custom/retrieval/generation node-local input
- Untrusted node output to schema validation and persisted state
- Broker message to tenant-scoped, terminal-guarded database transaction

## Data classifications

Workflow definitions and public node schemas are internal tenant data. Workflow inputs, retrieval
content, tool/custom outputs and intermediate state may be confidential or restricted. Credentials,
secret values, authorization context and raw sensitive provider/schema errors are restricted and
must never enter author-writable state, diagnostics, logs, metrics or traces.

## Authentication

Existing session/LDAP authentication protects operator authoring surfaces; consumer bearer tokens
protect runtime invocation. Mapping content never authenticates an actor, worker, tenant or event.
No new authentication mechanism is introduced.

## Authorization

Existing server-side object/action authorization remains authoritative at draft, publish, release
and execution boundaries. A mapped tenant/object/role/capability identifier is untrusted data and
must be tenant-scoped and re-authorized by the consuming service. Mapping cannot grant tool roles,
approve invocations, change release pins or alter runtime execution context.

## Tenant isolation

Mapping operates only on state already attached to the authorized run and on exact dependencies
pinned for that run's organization/release. Foreign identifiers in mapped data do not change query
scope. PostgreSQL tenant scope/RLS remains installed for database reads; mappings cannot select an
organization or bypass direct organization lineage.

## External systems

Model, embedding/retrieval, HTTP/MCP tools, custom nodes, broker and PostgreSQL are trust/failure
boundaries. P2.6.1 adds no endpoint or live egress. Existing provider outputs are untrusted,
schema/size bounded inputs to mapping.

## Abuse cases

- Use encoded pointer segments, aliases, case changes or Unicode confusables to write protected
  tenant, actor, authorization, capability, secret, release, budget or audit state.
- Use parent/child destination overlap or duplicate mappings to obtain order-dependent last-writer-
  wins behavior.
- Select ambient state into a tool/custom node beyond its field allowlist or output confidential
  node data to a later exfiltration-capable tool.
- Smuggle a foreign tenant/object ID through mapped business data and convince a downstream query to
  trust it.
- Use arrays, deep objects, many mappings or expanding transforms for memory/database/broker denial
  of service.
- Inject an expression/template/operation name that the runtime evaluates dynamically.
- Reference an inactive, foreign, mutable or `latest` transform profile to break release pinning.
- Exploit compiler/runtime parser differences or stale compiled checkpoints to bypass validation.
- Cause partial state mutation before a mapping/type/budget failure, then rely on redelivery to
  duplicate effects.
- Leak confidential paths/values, schema contents or provider errors through diagnostics/audit/logs.

## Failure cases

- Source path disappears or changes type between authored schema and runtime input.
- Node output violates its pinned schema or exceeds size/depth/item limits.
- Worker crashes before/after node execution or during atomic output mapping.
- Broker redelivers a mapping transition or delivers a stale compiler/checkpoint version.
- Transform dependency is disabled/missing/checksum-mismatched after authoring.
- State budget is exhausted after a valid but large output.
- Required audit persistence fails while committing a security/business transition.
- Mixed old/new workers interpret the same unreleased `agenthub/v1` node differently.

## Logging and audit risks

Pointer strings can reveal sensitive field names and mapped values may include personal data,
documents, secrets or provider responses. High-cardinality run, path, profile and tenant values can
overload metrics. Debug logging may accidentally serialize pre/post state or schema bodies. Audit
failure could leave a sensitive transition without required evidence.

## Mitigations

- One shared strict parser/canonicalizer used at author, compile and runtime boundaries
- Exact mapping schemas, allowlisted fields and deterministic conflict rejection
- Protected namespace registry checked on decoded canonical target segments, deny by default
- Node-local input envelopes plus existing tool/custom field allowlists and service re-authorization
- Immutable exact transform pins and closed operation registry; no expressions/templates/eval
- Compile-time schema checks where provable and mandatory pre-side-effect/runtime validation
- Atomic copy-on-success state transition with per-value and total byte/depth/item/entry budgets
- Immutable compiled contract version, worker compatibility checks and stale checkpoint denial
- Tenant-scoped database access/RLS and rejection of client-supplied ownership context
- Stable content-free errors, redacted bounded events and low-cardinality metrics
- Fail-closed required audit coupled to the state transition; optional telemetry fail open
- Capability gate, matching-worker rollout and no implicit database reset

## Residual risks

Schema compatibility may be undecidable for some external/custom output until runtime. Business data
that is legitimately visible to two allowed nodes can still be misused by an overly broad downstream
tool contract; existing tool field allowlists and release review remain necessary. Unicode field
names and future new server-owned namespaces require continuing registry/test maintenance. An
external side effect that succeeds before output mapping fails remains an ambiguous outcome owned by
P2.6.4; P2.6.1 must fail safely without automatic retry.

## Required security tests

- Authentication failure, author/release authorization denial and cross-tenant draft/profile access
- Every forbidden pointer syntax plus encoded, non-canonical, case/alias and Unicode bypass attempts
- Protected root and descendant writes from input, node output and transforms
- Duplicate/overlapping destination and deterministic-order conflict denial
- Foreign tenant/object identifier smuggling followed by downstream re-authorization denial
- Tool/custom input allowlist and retrieval ACL non-bypass through mappings
- Inactive/foreign/missing/checksum-mismatched transform profile denial
- Unknown operation/expression/template/injection-string rejection
- Per-entry, pointer, depth, array, object, expansion and total-state budget exhaustion
- Node output schema/type failure before commit; no partial state on any failure
- Duplicate delivery, stale task, cancellation, terminal resurrection and compiler-version mismatch
- Secret, confidential value, schema/provider error and sensitive path redaction in diagnostics,
  audit, logs, traces and metrics
- Required-audit persistence failure proves the security/business transition does not commit
