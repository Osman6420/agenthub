# Threat Model: staged-index-worker-rls-scope-fix

## Assets

- Tenant document bytes, parsed text, embeddings, summaries, and vector indexes
- Immutable artifact/profile pins and pipeline fingerprints
- Durable build jobs, outbox intents, progress, heartbeat, retry, cancellation, and result lineage
- Tenant isolation, build authority, and separate promotion authority
- Embedding/OCR/model credentials, endpoints, quotas, and provider spend
- Audit and operational evidence

## Actors

- Authorized document-set manager requesting/retrying/cancelling a build
- Release manager separately promoting a staged index
- Platform operator provisioning profiles/grants and operating OpenShift
- Ingestion worker consuming identifier-only Celery messages
- Malicious or compromised tenant user attempting cross-tenant references
- Stale, duplicate, delayed, or compromised worker/broker delivery
- External object-store and embedding/OCR/model providers

## Entry points

- Document-set build, retry, and cancel console endpoints
- Durable outbox dispatch and Celery `run_staged_index_build_job`
- Periodic reconciliation
- Operator preflight, logs, and any separately approved emergency runbook
- Object-store and external provider responses
- Privileged per-index store provision/retirement database functions, if approved

## Trust boundaries

- Browser/user to Django authorization boundary
- Django/web to PostgreSQL FORCE-RLS boundary
- PostgreSQL/outbox to Redis/Celery delivery boundary
- Celery message to authoritative job reloading and organization matching
- Worker to object storage and embedding/OCR/model egress
- Worker to per-index pgvector store and promotion boundary

## Data classifications

- Restricted: document bytes/text, embeddings, summaries, provider responses
- Secret: API tokens, object-store credentials, credential references when operationally sensitive
- Internal: endpoint/topology details, database roles, worker identities, trace/job references
- Tenant metadata: document/artifact/profile/index/job lineage and status

## Authentication

User authentication and existing platform/operator identity remain unchanged. Celery delivery is not
authorization: the worker must distrust payload authority and reload the job using only bounded
identifier/trusted organization metadata. External systems use deployment-resolved secrets only.

## Authorization

Existing exact document-set build/retry/cancel predicates remain authoritative. Promotion remains a
separate release-manager operation. The worker revalidates job organization, set state, immutable
profile/artifact lineage, tenant grants, and terminal/cancellation state before committing phases.

## Tenant isolation

Every protected-table query/mutation executes inside a short PostgreSQL transaction after
`set_tenant_context(authoritative_organization_id)`. Empty or wrong scope returns no rows and must
remain indistinguishable from unauthorized/missing data. Session-wide scope, owner/migration roles,
superuser, `BYPASSRLS`, disabled FORCE RLS, and client-supplied organization authority are forbidden.

## External systems

- PostgreSQL/pgvector: authoritative state, FORCE RLS, constraints, immutable per-index stores
- Redis/Celery: at-least-once delivery only
- S3/MinIO: untrusted document-byte transport with bounded reads
- Embedding/OCR/model providers: untrusted bounded egress with secret resolution, SSRF controls,
  timeouts, response-size/schema checks, and ambiguous-outcome handling

## Abuse cases

| Abuse case | Required mitigation/evidence |
| --- | --- |
| Forge organization header to load another tenant's job | Match header to authoritative job under exact scope; wrong/foreign scope denial test |
| Use a same-ID/foreign artifact or profile | Exact organization/type/status/grant re-resolution; cross-tenant negative tests |
| Re-enable processing by weakening RLS/DB role | Explicitly prohibited; deployment-role readiness and `NOBYPASSRLS` evidence |
| Duplicate/redeliver a costly provider build | Durable claim, bounded attempts, exact fingerprint, idempotent result linking, ambiguous outcome reconciliation |
| Cancel while external call is running, then accept late result | Recheck locked job/index state before every commit; late-result/cancellation test |
| Cause logs to disclose documents, vectors, endpoints, or secrets | Stable content-free error taxonomy, redaction tests, safe trace references only |
| Cross-tenant parent-vector reuse | Exact tenant/document-set/geometry/fingerprint validation plus FORCE-RLS copy test |
| Exhaust DB with build-long transactions | Short scoped DB phases; assert external calls occur outside the long transaction; transaction-age monitoring |
| Abuse privileged store DDL to create/drop arbitrary relations | Fixed `search_path`; integer-derived relation names only; authoritative scoped `IndexVersion` lookup and lifecycle checks; no caller-supplied SQL identifiers/types; revoke PUBLIC; application role gets EXECUTE only |
| Hijack a `SECURITY DEFINER` function through search-path or object shadowing | Schema-qualify trusted objects/operators where applicable, pin `search_path` to trusted schemas, own function with migration role, and test as the real non-owner role |

## Failure cases

- Missing scope or lazy ORM access returns `DoesNotExist`; classify safely and fail closed.
- Worker crashes between claim, external call, vector write, and finalization; durable reconciliation
  must distinguish proven local outcomes from ambiguous provider outcomes.
- Object-store, parser, embedding, OCR, vector DDL/write, progress, or audit failures leave no served
  partial index and retain bounded operator evidence.
- Stale mixed-version workers may continue reproducing the defect; rollout must prevent incompatible
  workers from sharing the ingestion queue.
- Progress/heartbeat failure must not authorize success; stale work enters reconciliation.

## Logging and audit risks

Raw exceptions can contain URLs, filenames, provider bodies, or document fragments. Persist and
render only allowlisted codes and safe job/index references. Audit request, claim, failure,
reconciliation, cancellation, retry, completion, and promotion separately. Metrics use bounded
state/failure-class labels and never tenant/job/document/profile identifiers.

## Mitigations

- Typed/explicit build inputs loaded from authoritative rows under exact tenant scope
- Short transaction-local tenant scopes for each DB phase
- No RLS bypass and no build-long transaction across external I/O
- Immutable pins, FK/lineage checks, row locking, active-build uniqueness, bounded retries
- Revalidation before commits, fail-closed cancellation/late-result handling
- Non-owner PostgreSQL/FORCE-RLS, cross-tenant, concurrency, and real-worker tests
- Privileged-function abuse tests for foreign/missing scope, invalid lifecycle, arbitrary IDs,
  identifier/type injection, active-store drop denial, and PUBLIC/no-role denial
- Staged rollout with compatible worker heartbeat/contract checks and bounded recovery

## Residual risks

- Phase splitting increases state-machine complexity and race surfaces.
- Provider-side work may complete when the local outcome is unknown; operator reconciliation remains
  necessary and blind retry remains prohibited.
- A local owner/superuser test environment can still mask future scope regressions unless the
  non-owner app-role gate remains mandatory.
- A separately approved emergency one-off build may hold a longer transaction and must be bounded,
  monitored, and treated as a temporary operational exception rather than the product fix.

## Required security tests

- Empty, wrong, malformed, and foreign organization scope fail closed.
- Cross-tenant job, artifact, profile, document set/version, membership, parent index, result index,
  retry, cancel, and reconciliation references are denied without disclosure.
- Same-tenant valid job succeeds under `NOSUPERUSER NOBYPASSRLS` with FORCE RLS enabled/forced.
- Celery payload cannot override tenant, profile, artifact, endpoint, credential, or promotion.
- Cancellation/late result, duplicate delivery, stale worker, max attempts, and ambiguous external
  outcome preserve lineage and never broaden authority.
- Logs, audit, UI, metrics, and traces contain no document text, embeddings, secrets, endpoints, raw
  provider bodies, or unbounded identifiers.
- Promotion remains denied to a build-only actor and requires the unchanged exact authority.
