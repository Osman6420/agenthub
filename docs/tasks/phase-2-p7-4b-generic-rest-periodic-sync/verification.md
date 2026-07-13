# Verification: Phase 2 · P7.4b generic REST + periodic incremental refresh

## Status

**Implemented and verified offline on 2026-07-13.** No live REST destination, credential, schedule
or connector request was configured. Live rollout remains a separate approval gate.

## Implemented evidence

- `RestPullProfile` is immutable/revisioned and platform-admin controlled. It fixes public HTTPS
  host/port/path prefix, GET or explicitly approved read-only POST, auth mode, secret reference and
  request/item/page/byte/time bounds.
- `RestPullContract` is an immutable tenant revision interpreted by a closed v1 schema: typed exact
  inputs, fixed relative paths, literal JSON trees with exact placeholder objects, RFC 6901 pointers,
  bounded pagination and inline UTF-8/base64 or fixed detail content. It has no URL/header/template/
  expression/plugin authority.
- Source creation requires an exact `(tenant, document set, profile)` grant and immutable profile +
  contract + document-set binding. New tenant tables have FORCE RLS policies.
- Sync is revision/checksum incremental, recoverable and snapshot-complete before missing-item
  reconciliation. A shared candidate helper preserves other source/manual members and emits no
  candidate when membership is unchanged. Confluence uses the same checksum/no-op behavior.
- The database-backed bounded interval scheduler covers Confluence and REST. It uses one schedule
  per source, unique slots, no catch-up storm, queued/running/retry backpressure and next-slot redrive
  of a broker-lost schedule-owned run.
- Incremental staged builds fingerprint embedding, parser, chunker and OCR configuration. Exact
  unchanged `DocumentVersion` rows copy only between the same tenant/document set/geometry/
  fingerprint; new or changed documents alone call the embedding provider.
- On-change modes are `draft_only`, `stage_only` and `promote_if_safe`. The last mode requires an
  exact release-manager-approved `project/scenario` target, rechecks current authority before work,
  clones the active release's immutable artifacts, runs the pinned eval and calls the existing
  promotion gate only on pass. Duplicate tasks retry while a claim is live; a claim older than the
  30-minute task limit plus a five-minute safety margin is safely reclaimable after worker loss.

## Security and authorization evidence

- Contract tests reject URLs, headers, templates/expressions, JSONPath, unknown keys, invalid RFC
  pointers, unsafe mapping keys, percent-encoded traversal and path/query injection.
- The transport validates every DNS answer through ADR-0005, pins the public IP while retaining TLS
  hostname verification, denies redirects and ignores response URLs. POST dispatch uncertainty is
  never retried; detail fetch is GET-only.
- Platform-only profile/grant operations, tenant-author source/run/schedule operations, exact grant,
  exact project/scenario target, revoked release-manager preflight and cross-tenant FORCE RLS paths
  are covered.
- Audits contain stable IDs, bounded counters and stable error codes; endpoint, query/input, cursor,
  title/content, secret and raw upstream exceptions are excluded.

## Verification results

| Check | Result |
| --- | --- |
| `.venv\Scripts\ruff.exe format --check .` | Pass — 341 files |
| `.venv\Scripts\ruff.exe check .` | Pass |
| `.venv\Scripts\mypy.exe apps config` | Pass — 340 source files |
| `manage.py makemigrations --check --dry-run` | Pass — no changes detected |
| `manage.py check` | Pass — 0 issues |
| P7.4b targeted SQLite | Pass — 20 passed, 1 PostgreSQL-only skipped |
| REST + staged-build targeted PostgreSQL/pgvector | Pass — 25 passed, 1 off-PostgreSQL guard skipped |
| Full SQLite | Pass — 561 passed, 25 skipped |
| Full PostgreSQL/pgvector with `--create-db` | Pass — 584 passed, 2 skipped |
| `git diff --check` | Pass |
| Production dependency diff | Pass — no dependency added; stdlib transport/interpreter |

The PostgreSQL run used `config.settings.local`, the local Compose PostgreSQL/pgvector service,
`MCP_ENABLED=true` and a non-empty test-only metrics token. The full SQLite run used
`config.settings.test`; both used the in-memory test object store where fixtures require it.

## Checks not run

- No live endpoint, DNS, TLS, credential, REST service, embedding provider, Celery broker delivery
  or production object-store smoke test.
- No browser/UI test because the visual contract/source/schedule editor is WS2 scope.
- No destructive migration reversal or production migration was run.
- No long-duration load, queue-capacity, embedding-cost or multi-Beat-replica soak test.

## Residual risks

- AgentHub cannot verify that an approved read-only POST is truly free of side effects.
- Upstream revision semantics may be weak; checksum fallback detects content changes only after a
  bounded fetch.
- An empty final snapshot produces an empty draft but cannot pass existing non-empty publication;
  automation fails closed and the prior active corpus remains served.
- Vector reuse saves embedding calls but increases PostgreSQL copy I/O and immutable-store storage.
- Dedicated connector Prometheus metrics/alerts remain an operations follow-up; durable counters and
  audit events are available now.

## Manual review required

Before live enablement, approve the immutable profile's endpoint/path/method/auth/secret, response
identity/revision/MIME/pagination contract, expected document and byte volumes, minimum schedule
interval and alert capacity. For automatic promotion, review exact `project/scenario` targets and
the empty-corpus behavior. WS2 owns the visual mapping editor; it must call these same backend
services and may not expose endpoint or secret details to tenant authors.
