# Verification — fixed vector storage assessment

2026-09-08. Documentation-only continuation of the RAG architecture review.

## Evidence

- Directly inspected `apps/ingestion/vector_store.py`: store_name:93,
  provision_store:127, search:303, drop_store:442 and related read/copy paths.
- Inspected `apps/ingestion/migrations/0015_index_store_ddl_functions.py`:
  SECURITY DEFINER provisioning creates tables at line 58 and search indexes at
  lines 75/82; RLS is forced at line 88.
- Confirmed staged_build references provision/copy/drop; inspected IndexVersion
  and the legacy static Chunk declaration in ingestion/models.py.
- Read ADR-0003 and repository planning/engineering/handoff rules. The active
  handoff concerns another task; none of its runtime assertions were relied upon.
- Consulted official pgvector v0.8.4 README sections on mixed dimensions,
  half-precision indexing and filtered approximate search. This verifies supported
  design options, not the installed extension version or performance here.

## Checks and limitations

- Checked local links in the four assessment files and whitespace in this unit.
- Reviewed additions to master-plan.md and archive/README.md; preserved pre-existing
  working-tree changes and previous archived assessments.
- No application tests, migration checks or benchmarks run in this continuation:
  no application code/configuration/schema changed. Prior task test counts are not
  presented as fresh evidence for this proposal.
- No service lifecycle action, live database inspection, data access or provider call.
  Current row/table counts and local service health were not revalidated.

## Final review

- Architecture: runtime DML only; fixed schema and indexes at deployment; physical
  table identity separated from logical generation identity. Multiple geometries
  require explicit supported search spaces. No new dependency or full rewrite needed
  to make this storage change.
- Security/authorization: preserve tenant FORCE RLS, document ACL/revocation checks,
  tenant-consistent writes and scoped maintenance; eventual DDL capability removal
  requires implementation review, not an action taken here.
- SRE: shared ANN selectivity, bloat, cleanup and concurrent generation lifetimes
  are explicit validation gates; no unsupported performance claims.
- Data/privacy and observability: no data or logging changes; future audit must
  avoid document/vector payloads and preserve lifecycle evidence.
- Residual assumptions: approved model catalogue and real workload size are unknown.
  Logical tenant isolation in a shared table is assumed acceptable; physical
  database separation would require a different deployment topology.
- Manual review required before implementation: institution's fixed-schema policy,
  model support, retention/retry windows, tenant isolation and migration/rollback plan.

Assessment is complete. Storage implementation remains unapproved and unimplemented.
