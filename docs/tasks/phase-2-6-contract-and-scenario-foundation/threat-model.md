# Threat Model: phase-2-6-contract-and-scenario-foundation

## Assets

- Tenant-scoped workflow state, artifacts, releases and run history
- Authorization/capability context and approval decisions
- Tool, retrieval, event and child-run inputs/outputs
- Audit lineage and immutable release/checksum evidence

## Actors

- Scenario authors, organization admins, platform admins and auditors
- Runtime workers and operators
- External event/tool/MCP systems
- Untrusted model output and malicious or compromised tenant users

## Entry points

- Workflow DSL and authoring/import interfaces
- Runtime task delivery and durable resume/event interfaces
- Tool/retrieval/child-run invocation boundaries
- Non-production fixture/seed and reset procedures

## Trust boundaries

- Browser/model/client to server canonical validation
- Web/compiler to immutable artifact and release compilation
- Broker task delivery to tenant-scoped runtime transaction
- Parent run to child workflow/agent authorization
- External tool/event output to persisted workflow state

## Data classifications

Workflow definitions and safe catalog metadata are internal tenant data. Runtime state, retrieved
content and tool results may be confidential. Credentials, secrets and authorization internals are
restricted and must not enter DSL, fixtures, diagnostics, logs or traces.

## Authentication

Existing authenticated server and worker identities remain authoritative. P2.6.0 must not assume a
future event correlation value alone authenticates an actor or external system.

## Authorization

Every action is checked for object, tenant and action authorization at execution time. Parent runs,
planner output, persisted state and client-supplied lineage do not confer authority.

## Tenant isolation

All proposed persistent records require direct organization lineage and PostgreSQL RLS/non-owner
verification where applicable. Scenario fixtures must include cross-tenant denial trajectories.

## External systems

Broker, PostgreSQL, tools, MCP servers, model providers and event producers are failure and input
trust boundaries. No live egress or credential provisioning is authorized by this task.

## Abuse cases

- DSL mapping writes protected tenant/actor/capability fields.
- Forged/replayed resume causes a transition in another run or tenant.
- Parent workflow invokes a child with broader capabilities.
- Duplicate tasks create duplicate side effects or resurrect terminal runs.
- Malicious tool/model/event output injects instructions or oversized state.
- A target fixture is imported before its compiler/runtime controls exist.
- A reset procedure targets an unknown or production-like database.

## Failure cases

- Worker crash between side effect and transition persistence
- Broker redelivery, stale task or concurrent resume
- Partial parallel completion and deterministic join conflict
- External timeout with ambiguous outcome
- Mixed old/new grammar or stale compiled release during cutover

## Logging and audit risks

Raw state, retrieved content, tool responses, credentials, Python source or hidden model reasoning
could leak through diagnostics. Audit and application logs could be conflated or omitted during
replay/recovery paths.

## Mitigations

- Declarative schemas, explicit allowlists and protected-key denial
- Immutable checksummed releases and server-owned lineage
- Transactional/idempotent transition contracts and terminal-state guards
- Capability attenuation plus child-boundary re-authorization
- Bounded state, concurrency, depth, duration and external input sizes
- Authenticated, replay-safe resume contracts to be decided before implementation
- Inert target fixtures outside import/seed paths
- Explicit database identity checks and separate destructive-operation approval
- Stable safe reason codes and redacted audit/telemetry contracts

## Residual risks

Exact join semantics, event transport, compensation behavior and child-run authority representation
remain design decisions. No dependent runtime work may treat them as settled before ADR review.

## Required security tests

- Unknown node/action/path/version rejection
- Protected-key and mass-assignment denial
- Authentication failure, authorization denial and cross-tenant access
- Forged, expired, replayed and wrong-state resume denial
- Duplicate delivery, stale result and terminal resurrection denial
- Child capability escalation, recursion and budget-amplification denial
- Secret/content redaction and bounded diagnostics
- Target fixture import exclusion and reset target fail-closed checks
