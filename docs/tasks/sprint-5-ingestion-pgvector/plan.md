# Task Plan: sprint-5-ingestion-pgvector

## Task summary

Implement Sprint 5's governed ingestion pipeline and tenant-filtered pgvector index.

## Background

Sprint 4 introduced retrieval/model provider seams but uses a static retriever. This
slice creates staged indexes from registered sources and supplies the real retrieval
provider without changing the gateway/runtime contract.

## Scope

- Source, IngestionRun, Document, IndexVersion, and Chunk models.
- Additive PostgreSQL pgvector migration and vector index.
- Atomic run claim plus source-scoped PostgreSQL advisory lock.
- Allowlisted HTTPS and S3/MinIO source connectors with bounded reads/timeouts.
- Parser, chunker, embedding, and index-writer registries.
- Celery ingestion task, retry/dead-letter, transactional audit, smoke retrieval.
- Tenant/index-version filtered pgvector retrieval provider.

## Non-goals

- Scheduling UI/API, OCR, arbitrary custom code, active-index promotion, production
  embedding vendor integration, or deletion/retention automation.
- Fetching arbitrary URLs or accepting credentials in source definitions.

## Acceptance criteria

- Two workers cannot process the same run or source concurrently.
- A successful run produces a staged, promotable index and queryable chunks.
- Terminal failures dead-letter the run and emit a redacted audit event.
- Retrieval filters organization and explicitly pinned index versions in SQL.

## Affected components

`ingestion` (new), `retrieval`, settings, dependency manifests, migrations, tests,
operations/current-state documentation.

## Interfaces affected

Internal Celery task and provider registries. No new public HTTP API.

## Data impact

Raw document text and chunk text are confidential tenant data. Embeddings and source
URIs inherit the source classification. Rows carry organization/source/index lineage.

## Security impact

Outbound connectors are deny-by-default with scheme/domain/size/time limits. Source
credentials are references, never inline values. Parser selection is an allowlist.

## Authorization impact

This slice has no end-user endpoint. Runs are created for registered tenant sources;
retrieval scope comes only from signed execution context organization and pinned index
ids. Cross-tenant ids must return no rows.

## Observability impact

Stable state transitions and counts are logged without content. Success, retry, and
dead-letter transitions are audited. Audit persistence is fail-closed for terminal
state changes.

## Migration impact

Additive tables plus PostgreSQL `vector` extension and vector index. SQLite tests use
portable model fallbacks; PostgreSQL integration is authoritative for vector/locking.

## Dependencies

Requires new production dependencies `pgvector` and `boto3`; explicit approval is
required before manifests are changed.

## Implementation steps

1. Add dependencies/app skeleton/models and additive migrations.
2. Implement connector and pipeline registries with bounded defaults.
3. Implement atomic claim/advisory lock, Celery task, retry/dead-letter and audit.
4. Add pgvector retrieval provider and runtime setting.
5. Add unit, concurrency/tenant-denial, failure, audit, and PostgreSQL integration tests.
6. Run all gates and record verification/operational guidance.

## Test plan

- Model invariants, state transitions, idempotent claim, retry limit, dead-letter audit.
- Concurrent source/run claim and PostgreSQL advisory-lock behavior.
- Connector SSRF/domain/scheme/timeout/size denials; no secret/content logging.
- Cross-tenant and non-pinned-index retrieval denial; ranking/top-k happy path.
- Migration apply/rollback smoke on PostgreSQL with pgvector.

## Rollout plan

Apply additive migration, deploy with no scheduled runs, smoke a small staged index,
then enable ingestion workers. Keep static retrieval provider until smoke passes.

## Rollback plan

Stop ingestion workers and restore the static retrieval-provider setting. Preserve
created data; schema removal requires a separately approved destructive migration.

## Risks

- Advisory locks and vector queries cannot be proven on SQLite.
- External documents may contain hostile prompt content; ingestion stores content but
  does not make it trusted. Runtime policy remains responsible for prompt-injection
  handling.
- Large documents/embedding batches can exhaust resources without strict bounds.

## Open questions

- Production connector domain allowlist and secret-manager integration values.
- Production embedding provider/dimension; this slice uses a deterministic test/dev
  embedder behind the registry seam.

## Status

Verified on SQLite and PostgreSQL/pgvector. Production connector destinations,
credentials, and embedding provider remain deployment configuration decisions.

## Completion criteria

All applicable Definition of Done gates pass, including real PostgreSQL/pgvector
locking and retrieval evidence; remaining connector/provider decisions are explicit.
