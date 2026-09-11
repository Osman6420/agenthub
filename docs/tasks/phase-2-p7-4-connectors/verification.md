# Verification: Phase 2 · P7.4 connectors

## Status

**P7.4a Confluence and P7.4b generic REST are verified offline as of 2026-07-13.** No
live Confluence/REST hostname, credential, CA, DNS policy, firewall rule or connector socket was
configured.

## Acceptance evidence

- ADR-0006 keeps existing model/embedding/OCR/tool destinations public-only and introduces a
  deployment-owned private-CIDR policy only for immutable Confluence profiles.
- ADR-0007 separates platform-owned REST destination/auth/method authority from a tenant-authored,
  closed JSON mapping. Unknown fields, URL/header/code/template surfaces and path escapes fail closed.
- Exact platform profile grants are tenant + document-set scoped. Runtime workers recheck immutable
  source/profile/contract bindings under transaction-local tenant context.
- Successful snapshots merge one connector slice with the trusted document-set baseline. Revisions
  and checksums prevent duplicate versions/candidates; only changed versions reach embedding.
- Periodic scheduling uses bounded intervals, unique slots, no backlog replay, source backpressure
  and same-run redrive for a schedule-owned queued/retry delivery lost by the broker.
- Optional `promote_if_safe` is candidate-idempotent, checks the current release-manager authority
  and exact scenario binding before publish/build, then uses the existing pinned eval and release
  promotion gates. Failure leaves the previous active release/index served.
- New tenant tables use PostgreSQL FORCE RLS. Compatible vector copy additionally requires the exact
  tenant, document set, geometry and pipeline fingerprint.

## Checks and evidence

| Check | Result |
| --- | --- |
| `ruff format --check .` | Pass — 341 files |
| `ruff check .` | Pass |
| `mypy apps config` | Pass — 340 source files |
| `manage.py check` | Pass |
| `makemigrations --check --dry-run` | Pass — `ingestion.0010` current |
| Targeted SQLite Confluence/egress/legacy ingestion | Pass — 41 passed, 2 skipped (P7.4a evidence) |
| Targeted PostgreSQL Confluence/FORCE RLS | Pass — 42 passed (P7.4a evidence) |
| P7.4b targeted SQLite | Pass — 20 passed, 1 PostgreSQL-only skipped |
| P7.4b + staged-build targeted PostgreSQL | Pass — 25 passed, 1 off-PostgreSQL guard skipped |
| Full SQLite suite | Pass — 561 passed, 25 skipped |
| Full PostgreSQL suite | Pass — 584 passed, 2 skipped |
| `git diff --check` | Pass |

Coverage includes private/public network boundary separation, fixed destinations/paths, response-link
non-following, uncertain-POST no-retry, percent-encoded path denial, exact grants, role and tenant
denials, immutable bindings, revision/checksum no-op sync, merged candidates, schedule backpressure,
lost-delivery redrive, revoked promotion authority, stale automation-claim recovery, PostgreSQL
FORCE RLS and exact compatible vector reuse with changed-only provider calls.

## Checks not run

- No live Confluence/REST request, corporate DNS lookup, TLS/CA handshake, secret-store resolution,
  service-account permission check, firewall verification or production object-store call.
- No dedicated live Celery broker delivery or scheduler multi-replica soak was run; offline/eager
  idempotency, redrive and source-backpressure paths are covered.
- P7.4b has backend services and management commands. Its visual REST contract/source/schedule
  editor is intentionally deferred to WS2.
- No destructive migration reversal was run. Additive forward migrations were exercised by fresh
  SQLite and PostgreSQL test databases.

## Residual risk and rollout gate

- The deployment must separately approve exact endpoint/path/auth/credential scope, identity and
  revision semantics, MIME/content limits, pagination, schedule capacity and alert thresholds.
- AgentHub cannot prove that a platform-approved POST endpoint is side-effect-free.
- Removing the final source document creates an empty draft; existing publication rules reject
  empty versions, so automatic staging/promotion fails closed until an explicit empty-corpus policy
  is approved.
- Dedicated connector Prometheus series are not added in this increment. Durable run/index counters
  and bounded audit events exist; production alerts remain rollout configuration.
- Confluence ACLs are an upstream import boundary. Imported content is subsequently controlled by
  AgentHub document-set/release/consumer ACLs rather than per-user Confluence ACLs.

## Manual review required

Approve each live Confluence network/CA/secret/service-account profile and each live REST
endpoint/credential/schedule before enabling it. For `promote_if_safe`, confirm the exact
`project/scenario` targets and release-manager ownership. WS2 should decide how empty-corpus removal
is presented and whether dedicated connector metrics are required before broad rollout.
