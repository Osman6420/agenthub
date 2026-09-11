# Local document ingestion smoke — 2026-07-16

## Objective

Verify the local upload → draft → publish → staged embedding index → promotion → scenario retrieval → authenticated gateway request path with a small synthetic text document.

## Scope and assumptions

- Local `demo` tenant only; no production systems or external provider calls.
- Use the configured deterministic embedding provider and existing PostgreSQL/pgvector, Redis and MinIO services.
- Create clearly named disposable smoke records where existing demo records cannot safely be reused.
- Do not reset the database or delete existing records.

## Trust boundaries and authorization

- Operator mutations must remain tenant-scoped and use existing domain services.
- Gateway access must use a newly issued, one-time plaintext REST consumer token bound only to the smoke scenario.
- Do not record token values or document content in logs or verification evidence.

## Operational and security risks

- An absent ingestion worker leaves authorized build jobs queued indefinitely.
- Promoting an index or release changes serving state; isolate the smoke scenario and document set.
- Retain synthetic smoke data after the run unless the owner explicitly authorizes deletion.

## Steps

- [x] Inspect the manual testing guide, canonical Compose topology and live health/process state.
- [x] Start one local ingestion worker and confirm it consumes the ingestion queue.
- [x] Create and upload a bounded synthetic `.txt`, then publish its document-set version.
- [x] Bind the set to an isolated RAG scenario, build and promote the staged index, and activate a compatible release.
- [x] Call the authenticated gateway endpoint and verify retrieval evidence.
- [x] Record identifiers, status transitions and verification results without secrets/content.

## Verification

- Live health and worker/process evidence.
- Database state transitions for document/set/index/release records.
- Authenticated HTTP response status and content-independent retrieval metadata.
- Bounded worker logs on failure.

## Rollback

Stop only the ingestion worker started for this smoke. Do not delete records or reset the database without explicit approval.
