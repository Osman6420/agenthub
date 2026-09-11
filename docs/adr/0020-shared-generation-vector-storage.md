# ADR-0020: Migration-owned shared vector storage

Date: 2026-09-09. Status: Accepted design; additive rollout in progress.

## Decision

Use one `SharedVectorChunk` table with exact tenant/generation/document lineage.
The finite cosine geometries are vector(64/768/1536) and halfvec(3072/4000).
Migrations own five expression/partial HNSW indexes, FTS and scope indexes.
Adding geometry requires a migration; profiles do not generate physical relations.
This supersedes ADR-0003's per-generation physical layout after verified cutover,
while retaining its immutable generations and metadata-only serving changes.

Each index records its storage layout. Legacy rows keep their original layout;
the shared writer is deployment controlled during rollout. Shared generations
move from new to open to sealed. Writes and copies lock authoritative generations;
database triggers enforce ownership, geometry, identity and immutability. Failed
build cleanup fences further writes before bounded deletion. During this additive
phase sealed generations cannot be deleted; full retention and worker-attempt
fencing remain acceptance criteria in the [single task](../tasks/Agent_Hub_MD/plan.md).

The same DAL serves vector/keyword retrieval, counts, preview, evidence and reuse.
The source-scoped legacy reader selects each generation's recorded layout. Existing
release, document and generation identifiers are preserved. Content authorization,
live grants and tombstones remain the caller's responsibility; table co-location
does not establish access or imply that embedding spaces are interchangeable.

Owner-only backfill copies bounded batches without provider calls or legacy
deletion. Exact `EXCEPT ALL` comparisons check full content/vector equality and
duplicate/extra rows; ordered SHA-256 fingerprints provide safe receipts. The
layout changes only after complete equality and an atomic audit record. Incomplete
copies remain invisible to normal legacy readers and can resume idempotently.

## Consequences

FORCE RLS and the non-owner role remain mandatory. The runtime needs SELECT,
INSERT and guarded DELETE on the shared table, with no UPDATE or schema ownership.
Fixed indexes reduce DDL proliferation but tenants and old generations compete
inside ANN indexes. Bounded iterative scans need pgvector >= 0.8.0; recall and
latency must be measured before enabling the shared deployment default. See
[pgvector filtering and iterative scans](https://github.com/pgvector/pgvector#filtering).

Old-reader/new-writer rollback is not safe merely because legacy tables remain.
Keep compatible readers, drain incompatible writers, verify backfill, then cut
over. Legacy DDL privilege removal, comprehensive retention, migration reversal,
mixed geometry/capacity and full browser verification are tracked in the task;
this ADR does not claim that rollout has completed.
