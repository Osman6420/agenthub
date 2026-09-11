# Local document ingestion smoke verification — 2026-07-16

## Result

Passed after starting the missing ingestion worker, configuring that worker and the smoke process
for the canonical local MinIO endpoint, and restarting the stale host-mode web/runtime processes.

## Evidence

- Infrastructure: PostgreSQL, Redis and MinIO reported healthy; `GET /v1/health/live` returned 200.
- Upload: authenticated console bulk-upload POST returned 302 and created document-set version 10.
- Publication: document-set version 10 reached `promotable` and was pinned in release 9.
- Ingestion: ingestion-queue task created index version 6 with one chunk; promotion changed it to `active`.
- Binding/release: isolated RAG scenario 16 (`smoke-doc-20260716-c`) was bound to document set 9;
  release 9 became `active` and pinned document-set version 10.
- ACL retrieval: direct tenant/consumer-scoped pgvector retrieval returned one hit containing the
  synthetic marker.
- Gateway: authenticated `POST /v1/query` returned HTTP 200, `status=completed`, one source,
  `fallback_used=false`, and an answer containing the synthetic marker.
- No bearer token or document body is recorded in this evidence.

## Failure diagnosis

The original stuck state was real: no process consumed the `ingestion` queue, while the console
only confirmed successful dispatch. Host-mode application processes also lacked the canonical
MinIO variables. A later endpoint-only 502 (`RETRIEVAL_FAILED`) disappeared after the documented
web/runtime restart; direct pgvector retrieval had already proved the index and ACL path healthy.

## Checks not run

No automated test suite, formatter, linter, type checker or migration check was run because this
task changed no application code or schema; it was a local operational smoke only.

## Residual state and risk

- Synthetic smoke records remain in the local `demo` tenant. Two earlier attempts may have left
  clearly prefixed partial records (`smoke-doc-20260716` and `smoke-doc-20260716-b`). They were not
  deleted because destructive cleanup was not authorized.
- The locally started ingestion worker remains running and listening only to `ingestion`.
- The UI still cannot distinguish “queued but no ingestion consumer exists” from healthy queue
  progress; operational monitoring/worker health exposure remains a product gap.
