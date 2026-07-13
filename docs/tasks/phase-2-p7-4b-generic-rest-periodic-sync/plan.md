# Task Plan: Phase 2 · P7.4b generic REST + periodic incremental refresh

Authority: [`phase-2-p7-4-connectors`](../phase-2-p7-4-connectors/plan.md),
[`document-plane-plan`](../../planning/components/document-plane-plan.md), and
[`phase-2-plan`](../../planning/phase-2-plan.md).

## Task summary

Implement a governed generic REST document-pull connector whose destination and credential remain
platform-controlled while an authorized tenant author can define the API's bounded request shape,
response projection, pagination, document identity, revision, and content mapping. Add periodic
refresh for Confluence and generic REST sources. A refresh creates work only for material document
changes; an incremental staged-index build copies compatible unchanged chunks/embeddings from the
previous immutable store and sends only new or changed document versions to the embedding provider.

The owner approved implementation on 2026-07-13. GET plus platform-profile-approved read-only JSON
POST, inline UTF-8/base64 and fixed detail fetches, periodic refresh, incremental embedding reuse,
and selectable gated automatic promotion are in scope. The initial operator surface is services and
management commands; the visual editor is deferred to the WS2 console redesign so two competing UIs
are not created.

## Background

- P7.4a already implements profile-only Confluence Data Center traversal and skips body fetches when
  `version.number` is unchanged.
- A fully successful Confluence refresh currently creates a new draft `DocumentSetVersion` even if
  membership is unchanged.
- `build_staged_index` currently parses, chunks, and embeds every member of every new set version.
  The blue/green store is correctly immutable, but it does not yet reuse unchanged rows.
- Celery worker/beat roles exist, but there is no database-backed per-source refresh schedule.
- Existing ADR-0005 public egress and ADR-0006 Confluence-private egress are authoritative. Generic
  REST remains public-unicast-only unless a future, separately approved ADR says otherwise.

## Design principles

1. **Generic mapping, non-generic authority:** authors describe data shape; only a platform profile
   chooses host, port, allowed path prefix, auth mode/secret, TLS, bounds, and egress policy.
2. **Declarative data, never code:** no Python, Jinja, JavaScript, JSONPath/JMESPath expressions,
   regex transforms, arbitrary headers, callbacks, plugins, deserialization hooks, or shell/code
   execution.
3. **Stable identity before incremental behavior:** every item must yield a stable external ID.
   Prefer an upstream revision; checksum fallback may avoid re-embedding but cannot avoid fetching.
4. **Immutable serving path:** refresh/build produces a new draft/staged candidate. Default behavior
   never changes serving; optional promotion calls the existing release-manager/eval/ACL gates.
5. **No-op means no work:** an unchanged snapshot creates neither a duplicate document version nor a
   duplicate set candidate/index build.

## Scope

### A. Platform-governed REST destination profile

Add an immutable, revisioned `RestPullProfile` managed by platform administrators:

- canonical HTTPS `base_url` split into scheme/host/port and a narrow allowed path prefix;
- public-unicast ADR-0005 validation, DNS-all-address validation, IP pinning, TLS/SNI, redirect
  denial, timeouts and response/total byte caps;
- platform-selected auth mode and `secret_ref`; initial recommended modes are `none`, `bearer`, and
  `api_key_header` with the header name fixed in the profile;
- allowed HTTP method(s) fixed by the profile, not by a source invocation;
- maximum items, requests, pages, retries, page size, nesting depth and decoded content bytes;
- immutable after use except disabling; endpoint/auth/limit changes create a new revision.

Add an exact `(organization, document_set, profile)` grant. A source cannot reuse the profile for a
different tenant or document set.

### B. Tenant-authored immutable pull contract

Add a tenant-owned, checksummed, revisioned `RestPullContract`. Authors may create a new revision;
used revisions are immutable. The backend validates and compiles the following closed schema.

#### Source inputs

The contract declares bounded named input fields (`string`, `integer`, `boolean`, bounded enum/list)
with length/range limits. A source supplies values for exactly those fields. Inputs cannot contain
headers, secrets, URLs, hostnames, TLS flags, network ranges, or object-store keys.

#### Request mapping

The request definition is a bounded JSON tree containing only:

- literal JSON scalar/list/object values;
- `{"$input": "field_name"}` references to validated source inputs;
- runtime pagination tokens from an exact allowlist: `$page_number`, `$offset`, `$page_size`, or
  `$cursor`;
- a relative collection path under the profile prefix; an input may occupy a whole URL-encoded path
  segment but cannot concatenate into or escape a path;
- query parameters and, if explicitly approved, a JSON request body built from the same safe tree.

No author-controlled header name/value is accepted. `Authorization`, `Host`, `Content-Type`,
`Accept`, tracing and user-agent headers are adapter-owned.

#### Response mapping

Use RFC 6901 JSON Pointers only. Pointers select values; they cannot filter, call functions, run
expressions, recurse, or construct paths. The contract declares:

- `items_pointer` to a bounded array;
- per-item `id_pointer` (required, canonical scalar);
- `revision_pointer` (recommended) and optional `deleted_pointer`;
- optional `title_pointer`;
- `content_pointer`, fixed/default MIME type, and content encoding (`utf8_text` initially;
  `base64` only if separately approved with decoded-byte limits);
- optional detail-fetch mode using a platform/profile-bounded relative path pattern and one
  URL-encoded ID segment; response-provided URLs are never followed;
- pagination mode: `none`, locally generated `page_number`, locally generated `offset`, or bounded
  opaque `cursor`. A response cursor may be copied only into the fixed cursor slot on the same
  profile/path; it is never interpreted as a URL, header, path, or secret. Cursor cycles fail closed.

Unknown keys and unsupported pointer/value types fail validation. A preview/validation operation
uses synthetic operator-supplied JSON and performs no egress.

### C. Generic REST sync lineage

Add additive, tenant-scoped `RestSyncRun` and `RestDocumentCursor` models plus RLS policies:

- cursor identity: `(source, external_id)`;
- upstream revision, content checksum, exact `Document`/`DocumentVersion`, last-seen run and state;
- run status/attempt, safe counters/bytes, snapshot-complete flag, material-change flag and candidate;
- source binds one exact profile, contract revision and document set; those bindings are immutable.

Sync behavior:

1. Claim the tenant-scoped run and source lock; re-check active profile, grant, contract and source.
2. Fetch bounded pages from server-constructed requests.
3. If external revision is unchanged, do not fetch/detail/decode content.
4. If revision changed or absent, compute SHA-256 over canonical decoded bytes. If checksum is
   unchanged, update cursor metadata without creating a `DocumentVersion`.
5. Persist new/changed bytes through the existing document upload service.
6. Only a fully successful snapshot reconciles missing/deleted items.
7. Compute the resulting membership fingerprint. If it matches the latest successful candidate or
   published set snapshot, finish as a no-op without creating another candidate.
8. Otherwise create one draft candidate. Apply only the schedule's authorized on-change mode.

Retrofit the same checksum/no-op candidate behavior into Confluence P7.4a.

### D. Periodic source refresh

Add a tenant-scoped `ConnectorSyncSchedule` for `confluence_dc` and `generic_rest` sources:

- one schedule per source; author-managed within the source tenant;
- bounded interval (15 minutes to 7 days), enabled flag and `next_run_at`; v1 deliberately has no
  tenant-authored cron, timezone or jitter expression;
- database time is authoritative; no tenant-authored cron expression/time zone in v1;
- a static Celery Beat dispatcher runs every minute and atomically claims due rows using
  `select_for_update(skip_locked=True)`;
- one unique schedule slot/run prevents duplicate enqueue across multiple beat replicas;
- if a source already has queued/running/retry work, skip backlog replay and move to the next slot;
  a schedule-owned queued/retry run whose broker delivery was lost is redriven at the next slot
  without creating a second run;
- source advisory locks remain the execution backstop; task payloads contain IDs only;
- manual sync remains available; disabling a schedule stops future enqueue but does not kill a
  running job.

No new scheduler dependency (`django-celery-beat`, etc.) is required.

### E. Incremental immutable index build

Extend `IndexVersion` with safe build provenance:

- `pipeline_fingerprint` covering exact embedding profile revision, dimensions/index type,
  chunker/version, parser pipeline version, and OCR profile revision when applicable;
- nullable compatible `parent_index_version`;
- embedded/reused document and chunk counters.

When building a published generated candidate:

1. Select the newest ready index from the same tenant/document set with the exact pipeline
   fingerprint.
2. Compare exact `DocumentVersion` IDs. A matching ID is immutable content and eligible for reuse.
3. Copy eligible rows with a parameterized `INSERT ... SELECT` between system-generated store names
   under the same transaction-local tenant RLS context.
4. Parse/chunk/embed only member versions absent from the parent store.
5. Omit removed versions from the new store.
6. Validate copied+embedded counts against the candidate membership and hard limits before marking
   the new store promotable.
7. On any failure, drop the partial new store; the parent/active store stays untouched.

A changed embedding profile, parser/chunker/OCR pipeline fingerprint, missing parent, retired store,
or failed count validation forces a full rebuild. Reuse is an optimization, never a correctness
shortcut.

### F. Operator surface

Backend services and management commands are mandatory. The WS2 console surface should allow an
author to:

- choose an already granted REST profile without seeing endpoint/secret details;
- create/revise a pull contract and validate it against synthetic JSON;
- enter exact source inputs, bind the document set, configure/disable the schedule, run now, and see
  safe status/counters;
- choose the on-change action described in Open questions.

All console requests call the same audited services; the UI is non-authoritative.

## Non-goals

- Arbitrary HTTP client/tool behavior, writes to upstream APIs, webhooks, callbacks, GraphQL, SOAP,
  browser/OAuth flows, cookies, arbitrary headers, response-provided URLs, file-server crawling, or
  remote code/plugins.
- Tenant-controlled destination, CIDR, proxy, CA, TLS switch, secret, auth header, retry policy, or
  redirect behavior.
- General transformation language, joins across endpoints, regex/HTML scraping, macro evaluation, or
  schema inference from live production responses.
- Ungated promotion or bypass of existing eval/release/consumer ACL controls.
- Reusing embeddings when any correctness fingerprint component differs.

## Acceptance criteria

### Flexible contract

- Two synthetic APIs with different request trees, item paths, identity/revision/title/content
  pointers and pagination modes are expressible without code changes.
- Invalid/unknown fields, deep/large mappings, forbidden placeholders, pointer errors, cursor cycles,
  path escape, headers, URL fields and executable/template syntax fail closed.
- A contract/source can never widen its profile destination, auth, document set or tenant.

### Change detection and indexing

- Unchanged revision avoids body/detail fetch and creates no document version/candidate/build.
- Changed revision with unchanged checksum creates no document version and causes no re-embedding.
- Changed content creates one immutable document version and one material candidate.
- Missing items reconcile only after a complete snapshot; partial failure leaves the prior candidate
  and active index untouched.
- A compatible incremental build copies unchanged rows and calls the embedding provider only for
  new/changed document versions. An incompatible fingerprint performs a full rebuild.
- Removed documents are absent from the new store; active serving remains unchanged until promotion.

### Scheduling and operations

- Due schedules enqueue at most one run per slot across concurrent dispatchers; no catch-up storm.
- Disabled, unauthorized, foreign-tenant, already-running and backpressured sources do not enqueue.
- Retry/dead-letter, source lock, task IDs-only payload, safe audit, counters and trace propagation are
  verified.
- Default configuration has no REST profile/schedule and opens no socket.

## Affected components

- `apps/ingestion`: profile/contract/source schema, transport/client, sync lineage/services/tasks,
  scheduler dispatcher, incremental staged build and vector-store copy operation.
- `apps/documents`: membership fingerprint/no-op candidate helper through audited services.
- `apps/console`: minimal contract/source/schedule forms and status views if approved in scope.
- `apps/tools`: reuse ADR-0005 validation and bounded HTTPS transport without weakening existing
  callers.
- `config/settings`: static beat dispatcher cadence and secure empty defaults.
- `deploy`: existing beat/ingestion workers only; no new service or dependency.

## Interfaces affected

- New internal management commands/services and console endpoints; no consumer gateway contract
  change.
- Celery tasks carry schedule/run/organization IDs only.
- New immutable tenant-authored REST pull-contract JSON schema.

## Data impact

- REST response content is confidential tenant document data stored as immutable object blobs.
- External IDs/revisions/checksums and safe counters are retained; raw request/response bodies,
  source inputs, endpoint/auth details and upstream errors are excluded from telemetry/audit.
- Reused vector rows duplicate unchanged text/embeddings into the new immutable store; retention
  remains governed by existing index retirement rules.

## Security impact

- Adds a new public egress caller but no new address class. ADR-0005 remains the network boundary.
- Tenant-authored mapping is untrusted data parsed by a closed interpreter. Destination/auth/header
  and authorization decisions never come from it.
- See [`threat-model.md`](threat-model.md).

## Authorization impact

- Platform admin: register/disable destination profile and grant it to an exact tenant+document set.
- Tenant author: create/revise contract, create source, configure schedule and request manual sync
  only inside the authorized tenant and exact grant.
- Consumer/retrieval authorization remains release-pinned document-set binding + effective grant +
  RLS; connector output cannot grant serving access.

## Observability impact

- Stable events for profile/contract/source/schedule create/update/disable, due-run enqueue/skip,
  sync start/retry/dead-letter/success/no-op, and staged build reuse/full-build outcome.
- Durable run/index counters and bounded-code audit events expose due/queued/skipped schedules,
  items/bytes/retries/change counts and embedded-versus-reused work. Dedicated Prometheus connector
  series and alert thresholds remain an operations follow-up; no tenant/page/URL labels are added.
- Audit persistence for administrative configuration changes is fail-closed. Worker operational
  event failure follows the existing durable-run recovery policy and must be documented explicitly.

## Migration impact

Additive migrations only:

- profile, exact grant, immutable contract revision, REST run/cursor and connector schedule tables;
- Source REST binding fields/constraints;
- IndexVersion parent/fingerprint/reuse counters;
- FORCE RLS on new tenant-scoped tables, with transaction-local tenant context and non-superuser
  PostgreSQL verification.

No destructive data migration or existing row rewrite is planned.

## Dependencies

No new production dependency is proposed. Use stdlib JSON/URL handling, existing JSON Schema
dependency where appropriate, existing bounded HTTPS transport, Celery/Beat, PostgreSQL and pgvector.

## Implementation steps

1. Owner decides the four open contract/automation questions below; update this plan and P7.4 threat
   model before code.
2. Add/accept an ADR for the tenant-authored REST mapping interpreter and incremental vector-row
   reuse invariants.
3. Implement closed contract schema/compiler and exhaustive malicious-input tests.
4. Add profile/grant/contract/source/schedule/run/cursor models, constraints, migration and RLS.
5. Implement platform/author services, commands and audit/redaction tests.
6. Implement bounded public-only REST client with injected offline transport and contract fixtures.
7. Implement recoverable snapshot sync, checksum/no-op behavior and Confluence retrofit.
8. Implement idempotent beat dispatcher and concurrency/backpressure tests.
9. Implement pipeline fingerprint and same-tenant compatible row copy; add real PostgreSQL tests that
   assert embedding provider call counts for changed versus reused versions.
10. Add operator documentation; defer the visual editor to WS2 as approved.
11. Run full SQLite/PostgreSQL gates, final staff/AppSec/SRE review, and update plans/handoff. Keep
    the rollout plan active until a concrete live profile is separately approved and evidenced.

## Test plan

- Contract unit/abuse tests: exact schemas, bounds/depth, pointers, placeholders, path encoding,
  input types, pagination/cursor cycles, forbidden URLs/headers/templates/expression strings.
- Transport tests: public-only DNS, mixed/private/rebinding denial, redirect denial, TLS hostname,
  fixed Host/auth headers, method/retry uncertainty, size/type/status failures.
- Authorization/RLS tests: platform and tenant role denials, exact grant, cross-tenant contract/source/
  schedule/run/cursor, forced RLS under non-superuser.
- Sync integration: revision fast path, checksum fallback, identity collision, duplicate IDs, partial
  failure, deletion reconciliation, retry/dead-letter/crash convergence and no-op candidate.
- Scheduler: frozen clock, concurrent beat claims, duplicate delivery, disabled/running/backpressure,
  no backlog storm and task payload redaction.
- PostgreSQL vector integration: exact compatible copy, only changed provider calls, removed rows,
  incompatible/full rebuild, RLS during copy, parent-retired race and partial-store rollback.
- End to end: synthetic REST → versioned documents → generated candidate → incremental staged index →
  eval/promotion → ACL-scoped retrieval; active release unchanged before promotion.
- Full repository format/lint/type/migration/SQLite/PostgreSQL/secret checks.

## Rollout plan

1. Deploy additive schema and code with dispatcher and all schedules disabled.
2. Register one synthetic/non-production public profile and least-privilege secret; validate contract
   preview offline, then run a bounded manual sync.
3. Prove no-op refresh and one-document-change incremental embedding counts.
4. Enable one schedule at the maximum interval; observe queue/bytes/retries/cost and disable on any
   unexpected behavior.
5. Expand per source after endpoint/path/auth/service-account and capacity review. Promotion remains
   manual/gated.

## Rollback plan

- Disable schedules and profiles first; queued runs fail closed at runtime re-authorization.
- Revert application code while retaining additive dormant tables/columns; no active index is
  mutated by refresh/build.
- Drop only failed/new staged stores through the existing audited retirement path. Never delete the
  previous active store or connector documents as rollback.
- Reverse schema only after confirming no deployed old/new mixed-version process relies on it;
  forward-fix is preferred.

## Risks

- A mapping language can become an SSRF/exfiltration/programming surface if placeholders, paths,
  headers or expressions grow unchecked.
- A POST-based "read" endpoint may have side effects or unsafe retry semantics.
- Weak revision fields can miss changes; checksum fallback detects content only after fetching.
- Incorrect pipeline compatibility could serve stale embeddings; default must be full rebuild on
  uncertainty.
- Frequent schedules can create queue/cost storms; intervals, one-slot claims, no catch-up and
  per-profile/source budgets are mandatory.
- Copying unchanged vectors trades embedding cost for PostgreSQL I/O/storage and must be measured.
- Automatic staging without promotion still spends embedding budget and can accumulate stores.

## Owner decisions

1. **HTTP method:** GET plus platform-profile-approved read-only JSON POST. POST is not retried after
   dispatch uncertainty unless a future immutable profile revision records a separately approved
   idempotency contract.
2. **On-change automation:** `draft_only`, `stage_only`, and `promote_if_safe`. Only a release
   manager can configure exact scenario promotion targets. The last mode publishes/builds/activates
   the new index, compiles a release from the active release's exact artifact refs, runs the existing
   pinned eval suite, and invokes the existing gated promotion only on pass. Any failure leaves the
   previous release/index active.
3. **Content modes:** inline UTF-8, bounded base64 for allowed document MIME types, and a fixed
   profile-prefix detail path. Response-provided URLs remain forbidden.
4. **Author surface:** backend services and commands in P7.4b; the visual contract editor belongs to
   WS2's console redesign.

## Status

**Implemented and verified offline on 2026-07-13.** Owner decisions are recorded above. No live
REST endpoint, credential or schedule was configured; those remain deployment rollout gates.

## Completion criteria

- Owner decisions and ADRs are accepted before implementation.
- Acceptance criteria map to recorded tests, including real PostgreSQL RLS and incremental vector
  reuse evidence.
- No new dependency, destination widening, ungated promotion, or executable mapping language.
- Current-behavior docs, parent/component/phase/master plans, handoff and verification are updated.
- Live endpoint/profile/secret rollout remains separately reviewed and evidenced.
