# Threat Model: sprint-5-ingestion-pgvector

## Assets

Tenant documents/chunks/embeddings, source configuration, index lineage, ingestion
state, and database/object-store availability.

## Actors

Authorized operators, ingestion workers, external HTTPS/object-store systems, and
runtime consumers acting through a signed ExecutionContext.

## Entry points

Internal run-creation service, Celery task payload containing only a run id, source
connectors, parser registry, and retrieval provider.

## Trust boundaries

Database to worker; worker to external HTTPS/S3; untrusted document bytes to parser;
signed runtime context to tenant-filtered vector query.

## Data classifications

Document/chunk content and embeddings inherit tenant source classification and may
contain PII or secrets. Logs/audit must contain identifiers and counts only.

## Authentication

No new public endpoint. External connector authentication uses future secret-manager
references; credentials are not stored in source config or task payloads.

## Authorization

Only registered sources may create runs. Runtime cannot supply organization scope;
the gateway-signed context supplies it.

## Tenant isolation

Every source/index/document/chunk is organization-derived. Retrieval applies both
organization id and pinned index-version ids in the database query.

## External systems

HTTPS sources, S3/MinIO, PostgreSQL/pgvector, Redis/Celery. All network calls require
timeouts, response-size limits, bounded retries, and configured destinations.

## Abuse cases

- SSRF/DNS rebinding or oversized/decompression-bomb document.
- Cross-tenant index id injection.
- Duplicate workers racing the same source.
- Malicious parser input or prompt injection stored as trusted instructions.
- Retry storm, poison document, or secret/content leakage in logs.

## Failure cases

Worker loss after claim, database/audit failure, connector timeout, parse/embed/write
failure, stale lock, partial index, and terminal retry exhaustion.

## Logging and audit risks

Exceptions can contain URLs/query strings or document content. Normalize reasons to
stable codes; do not persist raw exception strings, bodies, credentials, or vectors.

## Mitigations

Deny-by-default connector registry and destination allowlist; bounded byte/document/
chunk counts; safe parsers only; DB state machine; transaction boundaries; late Celery
ack; source advisory lock; staged index never auto-promoted; redacted audit; explicit
tenant/index SQL predicates.

## Residual risks

DNS pinning and production egress policy require infrastructure controls. The initial
deterministic embedder is not suitable for production relevance. Content-level prompt
injection remains governed by runtime policies rather than ingestion trust.

## Required security tests

SSRF scheme/host denial, size/timeout failure, invalid parser, cross-tenant retrieval,
unpinned index denial, duplicate claim, retry/dead-letter audit, and redaction tests.
