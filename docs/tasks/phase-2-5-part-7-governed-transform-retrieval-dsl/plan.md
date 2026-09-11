# Task Plan: phase-2-5-part-7-governed-transform-retrieval-dsl

## Task summary

Implement versioned, allowlist-only transform, chunking and retrieval contracts with deterministic
canonical validation, hard resource budgets and one shared preview/runtime executor. Tenant content
must never select Python, imports, network, filesystem, secrets or unbounded control flow.

## Scope

- Add a canonical immutable transform artifact contract and type-specific validators for transform,
  chunking and retrieval profiles.
- Implement an exact-key operation registry with versioned schemas and stable safe error codes.
- Support the Phase 2.5 initial operation families in bounded increments: record selection/filtering,
  field projection/rename/drop/default, text normalization/replacement, document mapping, bounded
  chunking and governed keyword/vector/hybrid retrieval configuration.
- Enforce global limits for body/input/output bytes, steps, expression depth, records, expansion,
  strings, generated documents/chunks and execution time checks.
- Use the same validator/executor for preview and ingestion runtime; preserve source identity and
  lineage through produced documents/chunks.
- Keep immutable artifact publication, exact release pins, tenant scoping and promotion gates.
- Add negative tests for unknown keys/operations, type confusion, malformed pointers, excessive
  depth/size/expansion and forbidden code/network/secret-shaped input.

## Non-goals

- Tenant Python, JavaScript, regex engines, templates with evaluation, plugins or dynamic packages.
- Joins across external endpoints, connector egress, secret resolution or filesystem access.
- Unbounded loops/recursion or arbitrary user-defined functions.
- OpenAI-compatible adapters, conversation persistence or the future broad workflow-node catalogue.
- Automatic publication, release promotion or migration of existing generic artifacts.

## Architecture

`apps.artifacts.validation` remains the immutable publication and release-compile authority. A new
pure DSL module owns exact schemas, canonical diagnostics and deterministic execution. Ingestion and
preview call this module rather than implementing parallel transformations. Retrieval providers
receive only a validated normalized profile; tenant/document ACL enforcement remains in the
provider and cannot be expressed or weakened by the DSL.

## Security and operational risks

- Expression or template features can become code execution: use closed data structures and no
  dynamic dispatch outside the platform registry.
- Record expansion and string operations can exhaust CPU/RAM: check budgets before and after every
  step and fail closed with stable codes.
- JSON Pointer traversal can expose unintended data or mutate input: operate on copied JSON values,
  reject dangerous/malformed paths and return explicit projections only.
- Retrieval metadata filters can bypass ACL: ACL scope remains server-owned and is intersected after
  profile validation; the DSL never accepts tenant, consumer, index or document-set authority IDs.
- Preview/runtime drift can validate one behavior and execute another: share the exact compiler and
  executor, and test canonical round trips.
- Diagnostics can leak content: return operation index/pointer and safe codes, never input values or
  raw exceptions; audit only artifact/checksum and aggregate counts.

## Implementation steps

1. Inventory existing artifact validators, ingestion chunking and retrieval profile consumers.
2. Define bounded v1 transform/chunking/retrieval schemas and stable diagnostics.
3. Implement the pure closed operation registry and deterministic executor with global budgets.
4. Wire type-specific immutable artifact validation and release compiler revalidation.
5. Wire governed execution into preview and ingestion without changing connector/ACL authority.
6. Add console/Studio authoring guidance and safe preview only after service contracts are proven.
7. Add unit, integration, authorization, redaction, compatibility and PostgreSQL/RLS tests.
8. Run full SQLite/PostgreSQL and static/schema checks without pytest `-q` or pytest timeout; update
   architecture, manual journey, Phase 2.5 status and verification evidence.

## Rollback

Remove additive validators/executor integration and stop accepting the new transform artifact type.
Existing immutable artifacts and releases are not rewritten or deleted. Existing ingestion defaults
remain available until governed profiles are explicitly pinned and activated.

## Status

Implemented and automated-verified. Immutable v1 schemas, closed operation registry, deterministic
bounded executor, chunking runtime, retrieval normalization/threshold enforcement, release compile
revalidation and ACL non-bypass regression are complete. Authenticated Turkish owner review remains.

## Completion criteria

All supported operations have exact schemas, hard limits, deterministic tests and safe failures;
preview/runtime equivalence and ACL non-bypass are proven; full SQLite/PostgreSQL/static evidence is
recorded; authenticated Turkish owner review is reported separately.
