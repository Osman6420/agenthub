# Threat Model: Phase 2 · P7.4b generic REST + periodic incremental refresh

## Assets

- Tenant document content, source inputs, external IDs/revisions and object-store blobs.
- Platform REST profile destination/auth/secret, egress policy and corporate network boundary.
- Immutable document-set/index versions, embeddings, active release pointers and retrieval ACLs.
- Scheduler/run state, queue capacity, embedding budget and audit/telemetry.

## Actors

- Platform administrator registering destinations/auth and exact tenant+document-set grants.
- Tenant author defining pull contracts, sources and schedules.
- Beat dispatcher and ingestion workers operating with identifier-only task payloads.
- External REST service and potentially malicious/compromised API responses.
- Malicious tenant author attempting SSRF, cross-tenant access, exfiltration or resource exhaustion.

## Entry points

- Profile/grant, contract/source and schedule management services/console/commands.
- Static Beat dispatcher and manual/queued sync tasks.
- REST JSON/status/header/content responses.
- Incremental index build and cross-store row-copy operation.

## Trust boundaries

1. Platform deployment configuration → immutable REST destination/auth profile.
2. Tenant-authored mapping/source inputs → closed contract compiler/interpreter.
3. Fixed governed request → public network → untrusted REST response.
4. Validated content → tenant object store and immutable document lineage.
5. Compatible immutable parent store → new staged vector store under tenant RLS.
6. Staged candidate → existing eval/promotion/ACL serving boundary.

## Data classifications

- REST profile secret: secret/highly restricted.
- Endpoint, path prefix, source inputs and network metadata: restricted operational configuration.
- Pulled document content and embeddings: confidential tenant data.
- IDs, counts, status/error codes and checksums: internal metadata; still tenant scoped.

## Authentication

- Human operations use existing authenticated operator identity.
- REST authentication is platform-profile-owned and resolved at dispatch time from `secret_ref`.
- No cookie/browser session, tenant-provided Authorization header or inline secret is accepted.

## Authorization

- Platform-only profile/grant administration.
- Same-tenant author-only contract/source/schedule/manual-sync operations.
- Exact profile grant includes document set; source cannot widen it.
- Runtime rechecks source/profile/contract/grant status after queue delay.
- Contract output is data only and never authorizes tenant, destination, document set or promotion.

## Tenant isolation

- Tenant ID derives from authenticated/server-loaded rows, never request/contract/response content.
- Tenant-scoped models carry organization columns, constraints and FORCE RLS.
- Tasks carry `(run_id, organization_id)` and filter both after setting transaction-local context.
- Cross-store vector copy requires same organization, document set and pipeline fingerprint under
  RLS; store names remain integer-derived and validated.

## External systems

- Platform-approved public HTTPS REST APIs only; ADR-0005 public-unicast validation applies.
- Redis/Celery for periodic dispatch; PostgreSQL/pgvector for schedule/run/vector state; object store
  for document bytes; embedding/OCR profiles for staged build.

## Abuse cases

| Threat | Mitigation |
| --- | --- |
| Mapping injects URL/header/secret or escapes path | Closed schema; profile-owned destination/auth/headers; relative prefix-bound path; whole-segment URL encoding; forbidden URL/header keys. |
| Template/expression executes or causes ReDoS | Exact placeholder objects and RFC 6901 pointers only; no template engine, regex, JSONPath/JMESPath, code or plugins. |
| Response supplies a next/detail URL for SSRF | Never follow response URLs; local numeric pagination or bounded cursor copied only into a fixed slot on the same profile/path. |
| DNS rebinding/private/metadata access | Existing ADR-0005 all-address public validation and pinned-IP TLS; redirect denial. |
| Shared profile exfiltrates tenant data to unintended endpoint/path | Exact tenant+document-set grant, narrow profile path prefix, least-privilege credential, bounded contract/source input; profile audit/review. |
| Cross-tenant source/run/cursor/schedule or vector reuse | Server-derived tenant predicates, model validation/constraints, FORCE RLS, exact compatible-parent checks and negative tests. |
| External ID collision overwrites another source/document | Unique `(source, external_id)` and server-derived logical ID containing source identity; conflicts fail closed. |
| Malicious cursor loops or grows unbounded | Cursor type/length cap, visited-token set, page/request/item/byte/time limits. |
| Revision lies or is absent | Prefer revision fast path; checksum fallback after fetch; document bytes immutable. Document the upstream consistency assumption. |
| Partial snapshot removes documents | Reconcile missing/deleted only after full successful traversal; partial run creates no candidate. |
| Incorrect embedding reuse serves stale vectors | Exact immutable DocumentVersion ID plus pipeline fingerprint; validate counts; any uncertainty/full incompatibility forces rebuild. |
| Schedule creates queue/cost storm | Bounded interval, unique slots, atomic claims, no backlog replay, queued/running/retry suppression, lost-delivery redrive, source lock and operational alerts. |
| POST read endpoint mutates or is retried unsafely | GET-only default; POST only by explicit profile approval with defined idempotency/retry behavior. |
| Logs/audit expose content, inputs, URLs or secrets | Stable codes, safe IDs/counts only; explicit redaction tests across debug/failure/retry paths. |
| Automation silently changes served corpus | Default `draft_only`; exact release-manager targets, candidate-idempotent claim, pinned eval and existing promotion gate. Prior active release remains served on failure. |

## Failure cases

- DNS/TLS/connect/timeout/status/malformed/oversized response: fail run; no reconciliation/candidate.
- Dispatch duplicate/beat concurrency: unique schedule slot and atomic claim produce one run.
- Worker crash after document persistence: checksum/version cursor convergence reuses persisted data.
- Worker crash after an automation claim: redelivery retries while the claim lease is live and may
  reclaim it after the 30-minute hard task limit plus a five-minute safety margin.
- Worker crash during vector copy/build: partial new store is dropped; parent/active remains ready.
- Parent retired between selection/copy: lock/recheck store readiness or fall back to full rebuild.
- Audit/config persistence failure: administrative change fails closed.
- Redis/worker outage: the schedule advances without catch-up; a schedule-owned queued/retry run is
  redriven on the next interval. Health/queue-age alerts must expose a prolonged outage.

## Logging and audit risks

- Request mappings and source inputs may contain business identifiers and must not be logged raw.
- URL/path/query, response item/title/content, cursors, headers, secrets, raw exceptions and vectors
  are forbidden in logs/audit/metric labels.
- Audit safe profile/contract/source/schedule/run IDs, actor, tenant, action, decision, outcome,
  stable reason, request/trace ID and bounded counters only.

## Mitigations

- Immutable/checksummed contract revisions, exact schemas and bounded interpreter.
- Profile-only destination/auth and existing SSRF-safe pinned transport.
- Exact tenant/document-set grant and runtime authorization recheck.
- Durable cursor/run/schedule state, source locks, unique schedule slots and fail-closed snapshots.
- Immutable parent/new stores, pipeline fingerprint and count-checked vector reuse.
- Explicit staged/eval/promote boundary and existing retrieval ACL/RLS.

## Residual risks

- An approved public endpoint/credential can still be compromised or return malicious content.
- Upstream revision semantics may be weak; checksum fallback costs network bandwidth.
- SQL row copying saves embedding cost but consumes database I/O/storage and may need load testing.
- A platform-approved POST endpoint cannot be proven side-effect-free by AgentHub alone.
- A declarative mapping language tends to accumulate features; every extension requires threat-model
  and compatibility review.
- A snapshot that removes the final document creates an empty draft, but existing publication rules
  reject empty versions; automatic staging/promotion therefore fails closed and needs an explicit
  product decision before an empty corpus can replace a served corpus.
- Dedicated connector Prometheus series/alert thresholds are not part of this backend increment;
  durable counters and bounded audit events exist, but production alerting still requires rollout
  configuration.

## Required security tests

- All mapping/path/header/URL/template/expression injection denial cases.
- SSRF rebinding/private/metadata/redirect/TLS and response-link non-following regression.
- Platform/author/foreign-tenant/ungranted/disabled authorization and audit denial.
- PostgreSQL FORCE RLS for contract/run/cursor/schedule and cross-store copy.
- Cursor/depth/item/request/byte/time limits, duplicate identity and partial snapshot behavior.
- Schedule concurrency/idempotency/backpressure and task-payload redaction.
- Exact provider call-count proof that only changed versions embed under a compatible fingerprint;
  incompatible fingerprint must full-build.
- Logs/audit/traces at success/retry/failure/debug asserted free of secrets, content, URLs, inputs,
  cursors and raw upstream errors.
