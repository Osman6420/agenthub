# Threat Model: phase-2-6-part-5-child-composition

## Assets

- Parent and child workflow/agent state and outputs
- Immutable parent/child release revisions, checksums, schemas and call-site policy
- Tenant, consumer, scenario, action and capability authorization
- Signed execution contexts and effective-capability checksums
- Cumulative depth, child, deadline, token, tool-call and state budgets
- Durable parent/child lifecycle, transition and audit evidence

## Actors

- Authorized scenario authors, operators and consumers
- Malicious or compromised tenant users/consumers
- Parent workflow and child workflow/agent runtimes
- Untrusted model, tool, retrieval and custom-node output
- Redis/Celery deliveries and reconciliation workers

## Entry points

- Authored/imported `subworkflow` and `agent_call` nodes
- Release-manifest child role bindings and activation
- Parent mapped state and call-site configuration
- Broker child-start/result/cancel messages
- Child output and failure/result metadata
- Authorized status, trace, eval and operator surfaces

## Trust boundaries

- Author/client DSL to canonical compiler
- Mutable role configuration to immutable parent release pin
- Parent run to child admission and fresh execution context
- PostgreSQL committed child intent to Redis/Celery delivery
- Parent mapped input to isolated child state
- Child output to schema/redaction validation and parent output mapping
- Live authorization policy to effective capability intersection
- Late/duplicate child result to terminal parent state

## Data classifications

Release-role metadata and safe schemas are internal tenant data. Parent input, child state,
retrieval/tool/model output and mapped result may be confidential or restricted. Credentials,
consumer tokens, signed contexts, secret values, hidden policy state and raw provider errors are
restricted and must not be copied into child state, links, logs, metrics, traces or audit metadata.

## Authentication

Existing consumer/session authentication remains unchanged. Child admission re-authenticates or
verifies the server-owned caller/service context and issues a new child-bound context. Parent state,
model output, broker possession and run/release/link IDs do not authenticate a caller.

## Authorization

Parent authorization is not delegated proof. Effective child capabilities are the intersection of
parent effective capabilities, compiled call-site envelope, child release/policy allowlists and
current tenant/consumer authorization. Server-side object/action authorization is then repeated for
organization, project, scenario, release, tool, retrieval and action access. Any missing/denied
source fails closed.

## Tenant isolation

Cross-organization composition is forbidden. Parent/child link records carry direct organization
lineage and use FORCE RLS where applicable. Every worker transaction installs tenant context before
resolving or locking records. Parent, child, role, release and checksum must resolve together under
the same server-owned lineage.

## External systems

PostgreSQL is orchestration authority; Redis/Celery delivery is untrusted and at least once.
Existing child tools, models, retrieval and custom-node providers remain separate governed trust
boundaries. P2.6.5 adds no endpoint, live egress or production dependency and does not make
ambiguous external effects safe to retry.

## Abuse cases

- Smuggle a capability/action through parent state, model output or broker payload.
- Bind a role to “latest,” substitute a new revision or invoke a foreign organization child.
- Give the child full parent state, token, credentials or hidden authorization context.
- Reset budgets at each child boundary to amplify calls, tokens, tools, state or duration.
- Create direct/indirect recursive calls or race admissions past depth/child limits.
- Forge child completion or replay output to mutate the parent twice.
- Race cancellation and result delivery to resurrect a terminal parent.
- Return oversized/deep/malformed output or write protected parent state through mapping.
- Trigger automatic retry after an ambiguous child side effect.
- Infer capabilities, business data or policy denials through logs/traces/metrics/errors.

## Failure cases

- Child release/grant is disabled between parent compilation and admission.
- Child contract/checksum or transition version does not match the parent pin.
- Broker fails after durable admission, redelivers, or a worker dies during execution.
- Parent cancels/terminates while child is pending or running.
- Child completes concurrently with cancellation or duplicate result consumption.
- Child exceeds deadline/state/token/tool budget or produces invalid output.
- Required authorization/audit persistence fails.
- Static cycle information is stale across separately promoted releases.

## Logging and audit risks

Parent/child input and output can contain personal, contractual or retrieved confidential content.
Capability lists and policy denial details may reveal security configuration. Raw signed contexts,
tokens, provider exceptions, mapped state and business identifiers must not enter application logs,
audit metadata or metric labels. Missing audit at admission/cancellation can hide authority use.

## Mitigations

- Exact immutable child role/revision/checksum pinning at parent release compile time
- Four-source capability intersection plus live object/action/tenant re-authorization
- Same-organization resolution and direct-lineage FORCE RLS records
- Fresh short-lived child-bound execution context; no parent token/context reuse
- Mandatory P2.6.1 input/output schemas, mappings, protected-key and size validation
- Separate child run and immutable idempotent parent/child link
- Transactional cumulative budgets, ancestry/depth guards and static call-graph checks
- Idempotent admission/dispatch/result/cancel commands with expected-state and terminal guards
- No generic retry/compensation of ambiguous effects before P2.6.4
- Redacted stable reason codes, safe checksums, bounded metrics and fail-closed required audit
- Disabled-by-default rollout and contract-version compatibility checks

## Residual risks

Live policy changes can invalidate a previously compiled relationship; runtime re-authorization
reduces but cannot remove operational race windows without a clearly defined admission snapshot.
Static cycle analysis across independently promoted releases requires bounded graph loading and may
be incomplete, so runtime ancestry guards remain necessary. Legitimately authorized nested calls
can still amplify cost within caps. P2.6.4 is required before generic recovery and reconciliation of
ambiguous child side effects can be enabled.

## Implementation status (2026-07-17)

Implemented and verified (disabled by default). Mitigations map to code as follows:

- Exact immutable child pinning → `apps/workflows/composition.pin_composition_children` +
  `apps/releases/compiler.role_accepts_artifact_type` (`child_workflow.`/`child_agent.` namespaces);
  runtime re-resolution + `COMPOSITION_CHILD_STALE` guard in `_resolve_active_child`.
- Four-source intersection + live re-authorization → `_effective_child_capabilities` (parent context
  caps ∩ compiled call-site envelope ∩ child-release allowlist ∩ live `ConsumerBinding`).
- Same-org + FORCE RLS → `WorkflowChildLink` (direct organization FK, `clean()` lineage checks,
  migration `workflows.0004` FORCE RLS provisioning, non-owner test).
- Fresh short-lived child context → `_issue_child_context` (new signed context, attenuated
  capabilities, `composition` claim; parent token/context never copied).
- Mapped-only input + untrusted output validation → `_validate_child_input`/`_validate_child_output`
  (child release input/output contracts), `_assert_mapped_size`, P2.6.1 mapping destination allowlist.
- Transactional budgets + ancestry/cycle guard → depth/child/cumulative-call/token guards + ancestry
  set in the signed claim; static self-cycle at compile time.
- Idempotent admission/dispatch/result/cancel + terminal guards → unique `(parent_run, call_site)`
  link, idempotent child idempotency key `comp:<run>:<node>`, terminal-status no-op in the Celery
  task, `cancel_children` propagation, post-commit resume signal.
- No generic retry/compensation of ambiguous effects → child failure/timeout/`outcome_unknown` map to
  a single stable terminal parent failure; explicit P2.6.4 integration seam left open.

Residual/unverified: real Redis/Celery worker-restart smoke; P2.6.4 error-route/compensation
integration; runtime nested-composition beyond leaf children exercised only via the ancestry/depth
guard, not a multi-level live scenario.

## Required security tests

- Each capability-intersection source independently removes authority and fails closed
- Missing/invalid authentication and signed child-context tampering
- Cross-tenant/organization role, release, link, run and broker payload substitution
- PostgreSQL non-owner/FORCE RLS denial for every new tenant-owned table
- Raw/latest/model-selected child reference and revision/checksum mismatch rejection
- Direct/indirect recursion plus exact/over depth, count and cumulative budgets
- Parent-state over-disclosure, protected mapping writes and oversized/deep input/output
- Duplicate/concurrent admission, dispatch, completion and cancellation
- Late result cannot mutate cancelled/failed/completed parent
- Child release/grant disable race fails closed
- Ambiguous external outcome is not automatically retried or compensated
- Required-audit failure blocks admission/security-sensitive transition
- Token, context, state, capability/policy detail and provider-error redaction
