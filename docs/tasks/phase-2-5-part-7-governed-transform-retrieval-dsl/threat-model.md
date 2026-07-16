# Threat Model: phase-2-5-part-7-governed-transform-retrieval-dsl

## Assets and boundaries

Restricted source records/document text, immutable DSL artifacts, document lineage, index contents,
retrieval ACLs and runtime resource availability cross browser/GitOps -> artifact validator -> pure
executor -> ingestion/index -> ACL-aware retrieval boundaries.

## Abuse cases

- Smuggle executable code, imports, endpoints, credentials or secret lookups through operation data.
- Trigger CPU/RAM exhaustion using deep expressions, large strings, expansion or excessive chunks.
- Use malformed pointers/prototype-like names to escape the intended record projection.
- Supply tenant/index/document-set/consumer IDs to widen retrieval authority.
- Exploit preview/runtime differences or nondeterminism to publish a body different from execution.
- Reflect restricted values or raw exceptions through diagnostics, logs or audit events.

## Required mitigations

Exact-key versioned schemas; closed operation dispatch; copied JSON values; no eval/import/network/
filesystem/secret API; pre/post step budgets; bounded expression depth; stable content-free errors;
canonical serialization; same preview/runtime executor; server-owned tenant and ACL intersection;
immutable exact release pins and fail-closed audit for durable mutations.

## Required tests

Happy path and canonical round trip; every unknown operation/key; invalid pointer/type/version;
step/depth/input/output/record/string/chunk limits; forbidden capability-shaped keys; deterministic
replay; source lineage preservation; cross-tenant forged pins; retrieval ACL non-bypass; diagnostic
redaction; audit rollback; SQLite plus PostgreSQL/RLS regression.

## Residual risk

Unicode normalization and token-count approximations need explicit documented semantics. Any future
regex, scripting, external enrichment or plugin operation requires a separate security approval.
