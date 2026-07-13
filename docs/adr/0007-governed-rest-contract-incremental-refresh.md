# ADR 0007: Governed REST pull contracts and incremental refresh

- **Status:** Accepted
- **Date:** 2026-07-13

## Context

P7.4b needs to import documents from APIs whose JSON shapes differ without turning AgentHub into a
tenant-controlled HTTP client or transformation runtime. Periodic refresh must avoid duplicate
document versions and embedding spend, while optional automatic promotion must retain the existing
release-manager, evaluation, immutable-index and ACL gates.

## Decision

- A platform-owned immutable `RestPullProfile` exclusively selects the public HTTPS host, port,
  path prefix, GET or explicitly approved read-only JSON POST, authentication mode/secret reference,
  retry semantics and resource bounds. ADR-0005 public-unicast DNS validation, pinned-IP TLS,
  redirect denial and response caps remain unchanged.
- A tenant author may create an immutable checksummed `RestPullContract`, but it is data rather than
  authority. Version 1 is a closed interpreter: typed source inputs, literal JSON trees, exact
  placeholder objects, whole path-segment input substitution and RFC 6901 pointers. Arbitrary
  headers, URLs, code, templates, regular expressions, JSONPath/JMESPath and response-link following
  are forbidden.
- A source requires an exact `(organization, document set, profile)` platform grant and binds one
  exact contract revision. Runtime workers re-check profile, contract, source and grant state.
- Pagination is locally generated page/offset state or a bounded opaque cursor copied only to one
  fixed query parameter on the same profile path. Cursor cycles fail closed. POST is never retried
  after an uncertain dispatch.
- Snapshot cursors use upstream revision as a fetch fast-path and SHA-256 over decoded bytes as the
  correctness fallback. Unchanged content creates no `DocumentVersion`. A complete snapshot merges
  the source slice into the newest trusted snapshot; unrelated source/upload memberships remain.
- A database schedule uses bounded intervals, a one-minute Beat dispatcher, tenant-by-tenant
  transaction-local RLS context, atomic claims, unique source/slot runs and no backlog replay.
- Incremental index reuse requires the same tenant/document set, exact immutable
  `DocumentVersion` ID and a fingerprint covering embedding profile/geometry, parser, chunker and
  OCR profile. Compatible rows are copied between integer-derived stores under tenant RLS.
- On-change automation is selectable: `draft_only` (default), `stage_only`, or
  `promote_if_safe`. Only a current release manager may configure exact bound scenario targets for
  the last mode. It compiles from the active release's exact artifacts, runs its pinned eval and
  calls the existing gated promotion only on pass. Duplicate delivery is candidate-idempotent.
- P7.4b provides backend services and commands; the visual editor is deferred to WS2.

## Consequences

The connector supports heterogeneous JSON APIs without a new production dependency or a general
HTTP/programming surface. Vector reuse trades embedding cost for PostgreSQL I/O/storage. An approved
read-only POST cannot be proven side-effect-free by AgentHub, so platform review and no-retry remain
residual controls. Default configuration has no profile, source or enabled schedule and opens no
socket. Live rollout still requires endpoint, credential scope, revision semantics and capacity
review.

## Migration and rollback

Migrations are additive: profile/grant/contract/source lineage, schedules/targets, automation claim
state and index provenance. New tenant tables use `FORCE ROW LEVEL SECURITY`. Disable the schedule
or profile to stop new work; previous document/index/release versions remain immutable.

## References

- [ADR-0003](0003-vector-storage-blue-green-per-index-version.md)
- [ADR-0004](0004-tenant-isolation-postgres-rls-connection-context.md)
- [ADR-0005](0005-shared-ssrf-safe-egress-adapter.md)
- [P7.4b plan](../tasks/phase-2-p7-4b-generic-rest-periodic-sync/plan.md)
