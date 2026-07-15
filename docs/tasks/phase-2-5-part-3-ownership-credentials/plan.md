# Task Plan: phase-2-5-part-3-ownership-credentials

## Task summary

Deliver Phase 2.5 Part 3: replace console-created projects' free-text ownership with a durable,
organization-scoped membership reference and add an administrator-only bearer consumer credential
lifecycle with server-generated consumer subjects, one-time token disclosure, rotation, revocation,
safe audit events, and additive compatibility migrations.

## Background

`AIProject.owner` is currently free text. The console limits its choices to membership usernames,
but persistence does not retain the membership or prevent later cross-organization drift. `Consumer`
creation still asks for an authentication subject, while bearer tokens can only be issued through a
management command. `ConsumerToken` already stores SHA-256 hashes and safe prefixes and the gateway
already rejects revoked tokens.

The owner authorized Part 3 implementation on 2026-07-15 by requesting that work begin. This is
explicit approval for the authentication, authorization, tenant-isolation, secret-handling, and
additive-migration changes defined here. It does not authorize OIDC, mTLS, public API changes,
production access, dependency changes, or destructive migration.

## Scope

- Add nullable `AIProject.owner_membership` pointing to `OrganizationMembership` with protected
  deletion and a same-organization application invariant.
- Backfill exact existing `owner` username matches without rewriting unmatched legacy owner text.
- Require console project owners to be active-organization memberships with role
  `organization_admin` or `project_owner`; persist the membership and derive the compatibility
  owner text from its user.
- Preserve explicit GitOps `owner` input and existing rows during the compatibility window.
- Remove editable bearer `Consumer.subject` from the console and generate an opaque,
  organization-unique, bounded-random subject server-side.
- Keep OIDC/mTLS/service-account subject entry out of the UI until those authentication modes are
  configured and separately approved.
- Add named bearer-token issue, rotate, and revoke POST actions to the consumer detail surface.
- Restrict credential mutation to platform or organization administrators of an active
  organization, rechecking authorization and tenant scope server-side.
- Show plaintext only in the immediate successful POST response, mark that response `no-store`,
  never persist the plaintext, and list only token name, safe prefix, status, and last-used time.
- Make issue/rotation/revocation and their success audit events atomic and fail closed if audit
  persistence fails. Repeated revocation is safe and cannot reactivate a credential.
- Preserve the management command, gateway bearer contract, existing tokens, MCP authentication,
  and current public endpoints.
- Update Turkish UI copy, architecture/current-behavior documentation, parent/master plans, and
  completion evidence.

## Non-goals

- OIDC/JWT, service-account, mTLS, certificate, IdP, Personal MCP, delegated identity, or new auth
  modes.
- Changing bearer token wire format, gateway/MCP endpoints, authorization headers, or runtime
  binding/capability rules.
- Removing `AIProject.owner`, changing the GitOps schema, or forcing unmatched legacy owners to a
  guessed membership.
- Membership CRUD, project reassignment UI, bulk rotation, automatic expiry, production rollout,
  or secret export/recovery.
- New dependencies, network access, destructive data changes, or legacy route removal.

## Acceptance criteria

1. Console-created projects store an eligible same-organization `owner_membership`; forged,
   ineligible, missing, and cross-tenant membership values are rejected server-side.
2. Existing project owner strings remain byte-for-byte unchanged; exact same-organization username
   matches are backfilled, unmatched/blank values stay safely nullable, and reverse/re-forward
   migration is documented and tested.
3. Deleting a referenced ownership membership is protected until ownership is reassigned or cleared
   through an approved path; project detail displays durable ownership with a legacy fallback.
4. Existing GitOps owner input remains compatible and does not acquire authority from free text.
5. Bearer-mode console consumer creation accepts only organization, display name, protocol, and
   status; forged `subject` input is ignored and a non-name-derived opaque subject is generated.
6. Only authorized platform/organization administrators of an active organization can issue,
   rotate, or revoke that organization's tokens. Anonymous, read-only, disabled-organization,
   cross-tenant, foreign-consumer, and foreign-token paths are denied without object disclosure.
7. Token plaintext is returned once on successful issue/rotation, is absent from database, session,
   messages, audit, logs, subsequent GET responses, and failure responses, and the reveal response
   is non-cacheable.
8. Rotation atomically revokes the selected active token and issues a replacement; revocation is
   idempotent, and revoked tokens immediately fail gateway/MCP resolution.
9. Audit events contain actor, action, consumer/token target, authorization outcome where the target
   is safely known, safe reason codes/prefix metadata, request/trace IDs when available, and never
   plaintext or token hashes. Credential mutation fails closed if its audit write fails.
10. Existing token-management command and bearer callers remain compatible; existing tokens and
    consumer subjects are not rewritten.
11. SQLite/PostgreSQL migration, authorization, RLS, redaction, gateway/MCP compatibility, static,
    schema, and full regression gates pass with recorded evidence.
12. Turkish owner and credential journeys receive owner review; no dependency, live egress,
    production, or destructive-data change is introduced.

## Affected components

- `apps/catalog`: project ownership model invariant, service, migration, and tests.
- `apps/tenancy`: membership relationship and protected ownership lifecycle behavior.
- `apps/identity`: consumer subject allocation and audited token lifecycle services/tests.
- `apps/console`: forms, views, URLs, templates, response-cache controls, and security tests.
- `apps/gateway` and `apps/mcp`: compatibility regression only.
- Architecture/current-behavior, Phase 2.5, master-plan, and task evidence documentation.

## Interfaces affected

- Operator console project and consumer forms.
- Additive console-only POST routes for token issue, rotation, and revocation.
- ORM schema gains nullable `AIProject.owner_membership`; no public JSON/API contract changes.
- Existing management-command arguments and gateway/MCP bearer interfaces remain unchanged.

## Data impact

- Existing project rows may gain an FK to an exact same-organization membership; owner strings are
  retained.
- New console consumers receive random opaque subjects. Existing subjects are unchanged.
- Token plaintext exists only in process memory and one HTTPS/HTML response; only hash and safe
  prefix remain durable.

## Security impact

- This is an approved authentication/secrets change. Credential mutations are default-deny,
  CSRF-protected, POST-only, tenant-scoped, non-cacheable at disclosure, and transactionally audited.
- Random values use `secrets` with bounded collision retry. No plaintext enters persistence,
  telemetry, exception text, messages, or URL/query parameters.
- Membership and opaque identifiers are locators, never authorization.

## Authorization impact

Credential lifecycle requires `can_admin_org`; project creation retains `can_admin_org` and adds an
eligible same-organization membership check inside the domain service. Disabled organizations deny
all mutations. Foreign and missing targets remain indistinguishable after membership-scoped lookup.

## Observability impact

- Add stable actions `consumer_token.issue`, `consumer_token.rotate`, and
  `consumer_token.revoke` with low-cardinality safe reason codes.
- Reuse request/trace correlation when exposed by the request middleware.
- Do not add subject, UUID, token ID, prefix, hash, or plaintext as metric labels.
- Credential mutation uses fail-closed audit persistence in the same database transaction.

## Migration impact

Add `owner_membership` nullable with `PROTECT`, then backfill only exact
`organization + user.username == owner` matches. The reverse migration clears only the FK and does
not touch compatibility text. Keep the field nullable for unmatched legacy/GitOps records. Test
forward, reverse, and re-forward on SQLite and PostgreSQL. Application rollback retains the
additive column; no emergency drop is permitted.

## Dependencies

No new dependency. Use Django, Python `secrets`, existing tenant predicates, token hashing, audit,
and transaction infrastructure.

## Implementation steps

1. Capture focused baselines and inventory project-owner, consumer-create, token, audit, gateway,
   MCP, migration, and RLS seams.
2. Add the ownership FK, exact-match data migration, model/service invariant, scoped form, and
   compatibility tests.
3. Add opaque consumer subject allocation and route console creation through an atomic service.
4. Add audited token lifecycle services with locking, bounded generation, idempotent revocation,
   atomic rotation, and safe result types.
5. Add POST-only console handlers, forms, URL routes, one-time no-store disclosure view, and Turkish
   token metadata/actions.
6. Update management-command reuse without changing its CLI contract; add gateway/MCP and
   redaction regression tests.
7. Update architecture/current-behavior docs and execute focused, migration, static, full SQLite,
   and PostgreSQL verification.
8. Review the final diff as staff engineer, AppSec, and SRE; record evidence, residual risks, and
   owner manual-review items.

## Test plan

- Ownership: exact-match backfill, unmatched/blank preservation, reverse/re-forward, role filter,
  forged/cross-org membership, service recheck, protected deletion, detail fallback, GitOps parity.
- Subject: entropy/shape/length, collision retry/exhaustion, forged subject, transaction rollback,
  existing-subject preservation, non-disclosure.
- Credentials: issue/rotate/revoke happy paths; raw/hash/prefix assertions; repeat revoke; inactive
  token/consumer; audit failure rollback; no-store headers; plaintext absence from persistence,
  messages, audit, GET and errors.
- Authorization: anonymous, CSRF/method, auditor/project-owner/scenario-editor, organization admin,
  platform admin, disabled org, malformed/missing/foreign consumer and token, cross-tenant RLS.
- Compatibility: management command, gateway, MCP, existing token resolution and bindings.
- Gates: Ruff format/check, mypy, Django check, migration drift, compileall, focused and full
  SQLite/PostgreSQL tests, secret scan, documentation links/fences, `git diff --check`.

## Rollout plan

1. Apply the additive ownership migration and verify matched/unmatched counts without logging owner
   values.
2. Deploy code that writes durable ownership and server-generated subjects, then enable token UI.
3. Verify denial, audit, no-store, rotation/revocation, gateway/MCP, error-rate, and migration
   evidence in a non-production environment.
4. Production activation remains under the separate Phase 2 closure approval.

## Rollback plan

- Roll back application code while retaining the nullable ownership column and legacy owner text.
- Keep existing consumer subjects and tokens; disable the new console actions without changing
  gateway authentication.
- Never restore access by weakening role, tenant, CSRF, audit, hashing, or RLS controls.
- Reverse the data migration only by clearing the additive FK; do not delete memberships, projects,
  consumers, or tokens.

## Risks

- A forged or stale membership could create cross-tenant ownership without service/model checks.
- `PROTECT` can block membership/user removal until an owner is deliberately reassigned.
- One-time plaintext can remain in browser memory/history unless the response is no-store and the
  operator stores/closes it promptly.
- Audit failure handling could accidentally leave a usable credential without evidence unless the
  audit and mutation share one transaction.
- Rotation races could leave multiple active tokens or revoke the wrong token without row locking.
- Legacy free-text GitOps ownership remains non-authoritative until a separately designed declarative
  membership reference exists.

## Open questions

- Owner review must decide whether a future GitOps contract should accept a durable membership/user
  locator; this part preserves the current string contract.
- Automatic token expiry and last-used retention are deferred; they require a separate lifecycle
  and compatibility decision.

## Status

Verified on 2026-07-15. Scope and security gates were owner-approved; implementation, SQLite and
PostgreSQL automation, migration/RLS, authorization, audit rollback, debug-response redaction,
gateway, and MCP compatibility evidence are recorded in `verification.md`. Completion/archive is
pending the owner's Turkish browser journey review; no live development or production database was
migrated as part of automated verification.

## Completion criteria

Map every acceptance criterion to `verification.md`; pass applicable Definition of Done gates;
record SQLite/PostgreSQL migration and non-owner tenant evidence; complete staff/AppSec/SRE review;
update current-behavior and parent/master plans; obtain Turkish journey owner review before archival.
