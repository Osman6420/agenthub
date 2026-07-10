# Threat Model: sprint-8-workflow-core

## Assets

Workflow definitions and compiled graphs, contracts, release pins, custom-node
registry/packages, tenant data, runtime state, run integrity, provider budgets,
evaluation evidence, audit history, and service availability.

## Actors

Project editors, release managers, platform package maintainers, consumers, workers,
providers, malicious tenant users, and compromised custom-node authors/packages.

## Entry points

GitOps/artifact import, compiler and diagnostics, release compilation, gateway/MCP
invocation, run status/cancel, worker messages, node configuration, custom-node
manifests/packages, and evaluation cases.

## Trust boundaries

Authored DSL to compiler; compiled graph to runtime; queue message to worker; workflow
state to node; platform image/package to custom-node registry; node to model/retrieval
providers; run/eval output to release gate.

## Data classifications

Workflow metadata is internal. Inputs, state, retrieval, model output, and eval cases
may be confidential/PII. Secrets and consumer credentials are restricted and must
never enter node state. Checksums, statuses, and redacted events are internal.

## Authentication

Existing operator and consumer authentication applies. Worker messages are accepted
only through the approved broker and re-resolve authoritative run/release state; a
message payload is not an authenticated tenant decision.

## Authorization

Server-side checks cover artifact/version authoring, compile/publish, release pins,
invoke/status/cancel, and custom-node selection. Runtime authorizes the pinned release
and approved node version, not arbitrary node references from request/state.

## Tenant isolation

Workflow, scenario, release, run, contracts, retrieval index, and custom-node allowlist
must resolve within one organization. All durable lookups and status/cancel operations
use the authenticated/effective tenant context.

## External systems

Postgres, Redis/Celery, model and retrieval providers, object store, package registry,
CI/image registry, and telemetry backends. Custom nodes have no direct network access;
approved provider calls retain destination/time/size limits.

## Abuse cases

- Embed code, templates, unsafe expressions, endpoints, secrets, or package entrypoints
  in DSL/configuration.
- Construct cyclic, branching, deeply nested, or high-output graphs for denial of service.
- Reference another tenant's workflow, contract, index, run, or custom node.
- Modify raw YAML after compile or substitute an unpinned graph/package at runtime.
- Exploit a custom node to access DB, filesystem, environment secrets, or network.
- Poison workflow state or model output to bypass conditions/policy/output validation.
- Replay worker tasks to duplicate costly or stateful work.

## Failure cases

Compiler/runtime version skew, unavailable package/provider/broker, worker crash between
state and event writes, retry/redelivery, cancellation race, partial node output,
oversized state, stale release cache, and audit persistence failure.

## Logging and audit risks

State patches and diagnostics may contain prompts, retrieved text, model output, or
secrets. Store checksums, field paths, node IDs/types, sizes, and safe reason codes;
redact/truncate trajectory payloads. Audit mutations and authorization decisions, not
full workflow state.

## Mitigations

Strict versioned schemas; non-executable condition allowlist; deterministic compile and
checksum; immutable release pins; graph/state/step/time/output bounds; transactional
state transitions and idempotent claims; post-node contract/policy validation;
pre-installed allowlisted custom nodes with restricted context; tenant-scoped queries;
redaction; retention; package provenance and image compatibility checks.

## Residual risks

In-process custom nodes share the worker's OS privileges and a compromised approved
package may escape application-level restrictions. Model prompt injection can influence
allowed branches despite policy. External provider side effects/cost cannot always be
undone after cancellation.

## Required security tests

Code/expression/template/endpoint injection denial; graph/state resource bounds;
cross-tenant reference/status/cancel denial; compiled checksum/package substitution
denial; custom-node inactive/unallowed/context/network/secret tests; worker replay and
concurrency; output-policy enforcement; redaction; audit-failure behavior; and malicious
model/retrieval state tests.
