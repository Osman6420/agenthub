# Database architecture and simplification review

## Scope and outcome

Inspect the current working-tree models, migrations, services, tests and architecture decisions. Inventory fixed and dynamically created tables; distinguish required lifecycle/security boundaries from consolidation candidates. Deliver an evidence-backed assessment in Turkish with staged recommendations.

## Non-goals and boundaries

No application code, database data, schema, authentication, authorization, dependencies or runtime lifecycle changes. Existing unrelated working-tree changes remain untouched. Local database inspection, if available, is read-only and limited to schema and aggregate metadata; no document text, credentials or personal records.

## Acceptance criteria

- [x] Enumerate current model tables and reconcile with migration state and local schema where available.
- [x] Trace candidate simplifications through readers, writers, constraints and relevant tests.
- [x] Explain necessary separations, duplication, risks and a prioritized migration strategy.
- [x] Record evidence, limitations and review; archive this assessment and link it from the master plan.

## Risks and assumptions

Table count does not establish cost or redundancy. Empty local tables do not establish production disuse. Generic grants or JSON consolidation can weaken foreign keys, tenant isolation and auditability. Dynamic vector stores have dimension/lifecycle constraints. The working tree includes ongoing changes, including an ingestion migration; findings refer to this checkout, not a released baseline.

## Verification

Use current Django model metadata, migration graph, exact references, targeted source/test inspection, and optional local PostgreSQL catalog/aggregate queries. No performance claims without measurements. No full application test suite is required for documentation-only analysis; check resulting documentation links and diff.

## Status

Completed 2026-09-08; archived under this stable review identifier. Implemented: [assessment](assessment.md), [inventory](inventory.md) and review documentation only. Verified: model/migration/live table-name reconciliation, migration drift check, 60 passing targeted tests (2 PostgreSQL-only skips), documentation links and scoped diff; see [verification](verification.md). No application simplification implemented, no durable architecture decision adopted, and no replacement implementation plan. Existing current-behavior documentation remains authoritative.
