# Threat Model: phase-2-5-part-3-ownership-credentials

## Assets

- Bearer token plaintext, hashes, safe prefixes, status, rotation/revocation state, and last-use time.
- Consumer identity, organization lineage, bindings, capabilities, grants, and invocation authority.
- Human membership identity, role, project ownership, and tenant boundary.
- Immutable audit evidence and request/trace correlation.

## Actors

- Platform administrators and organization administrators authorized to manage credentials.
- Project owners, scenario editors, release managers, approvers, auditors, and ordinary members who
  must not manage credentials unless separately authorized.
- Consumer applications presenting bearer tokens.
- GitOps/management-command operators using existing compatibility interfaces.
- Anonymous, compromised, malicious, or cross-tenant users.

## Entry points

- Console project and consumer creation forms.
- Consumer detail token issue, rotate, and revoke POST routes.
- Existing `create_consumer_token` management command.
- Gateway `/v1/*` and MCP bearer authentication.
- ORM/service calls, migrations, membership deletion, and GitOps project upsert.

## Trust boundaries

- Browser form/URL/POST data to authenticated Django console.
- Session authentication and CSRF boundary to server-side role and tenant authorization.
- Console/service layer to PostgreSQL transaction, RLS, and append-only audit storage.
- Plaintext token process memory/HTML response to operator secret storage.
- Bearer header to hash comparison and consumer/binding authorization.
- Legacy owner text to durable organization membership; text is untrusted and non-authoritative.

## Data classifications

- Token plaintext and hashes: secret/restricted.
- Prefix, status, token name, subject, membership/user locator, last use: sensitive operational
  metadata.
- Display names and Turkish help text: internal.
- Audit actor/action/outcome/reason/target: security audit data.

## Authentication

- Console uses the existing authenticated LDAP/session user contract; no client-supplied role or
  organization is trusted.
- Gateway/MCP continues hashing bearer tokens and accepts only active tokens for active consumers.
- OIDC, JWT, service account, and mTLS are not introduced.

## Authorization

- Credential mutation requires `can_admin_org` after membership-scoped consumer resolution.
- Project creation requires existing admin authorization plus an eligible same-organization owner
  membership checked in the domain service.
- Token IDs, public UUIDs, subjects, prefixes, membership IDs, and legacy owner strings grant no
  permission.

## Tenant isolation

- Resolve consumers through the actor's allowed organizations before token lookup.
- Scope token lookup to the already-authorized consumer and organization.
- Validate ownership membership organization at form, service, and model boundaries.
- Preserve direct `organization_id` token lineage and PostgreSQL FORCE RLS; test non-owner roles.

## External systems

None added. Browser/operator secret storage is outside the application trust boundary. Existing
LDAP and gateway/MCP consumers remain unchanged.

## Abuse cases

- Forge a foreign membership ID to assign a cross-tenant owner.
- Forge a consumer UUID or token ID to rotate/revoke another tenant's credential.
- Use read-only membership or disabled organization to issue credentials.
- Submit GET or CSRF-less POST to trigger token mutation.
- Recover plaintext from database, audit, session, message, logs, cache, referrer, or later GET.
- Race two rotations/revocations to preserve or create unintended active credentials.
- Trigger audit failure after token creation to obtain an unaudited credential.
- Exploit generated-subject collision or input smuggling to choose an authenticated subject.
- Delete an owner membership to orphan a project silently.

## Failure cases

- Random collision, database integrity error, or retry exhaustion.
- Audit persistence failure.
- Missing, already revoked, stale, or foreign token.
- Membership removed or role changed between form validation and save.
- Transaction deadlock/serialization failure during concurrent rotation.
- Browser refresh/retry after one-time disclosure.
- Reverse migration after code rollback.

## Logging and audit risks

- Plaintext/hash exposure through exception formatting, POST logging, audit `reason`, messages, or
  test failure output.
- Prefix/subject/UUID cardinality in metrics.
- Missing denial evidence or audit written outside the credential transaction.
- Audit target leakage when a foreign object must remain indistinguishable from missing.

## Mitigations

- `secrets` generation, SHA-256 hashes, bounded retry, server-generated subjects, and strict forms.
- POST-only, CSRF, session auth, `can_admin_org`, disabled-org denial, scoped lookup, RLS, and row
  locking.
- Atomic mutation plus audit, with fail-closed rollback on audit failure.
- One-time dedicated HTML response with `Cache-Control: no-store`, no raw token in URL/session/
  message/audit, and safe generic errors.
- `PROTECT` ownership FK, exact-match backfill, same-org/eligible-role service validation, and model
  invariant.
- Idempotent revoke and active-state precondition for rotation.
- Low-cardinality reason codes and no secret/high-cardinality metric labels.

## Residual risks

- An authorized administrator or compromised browser can copy/exfiltrate the one-time plaintext.
- `PROTECT` requires operational reassignment before membership/user deletion.
- Legacy GitOps owner text remains a compatibility label, not durable authority.
- No automatic token expiry exists; manual rotation/revocation remains operationally required.
- Application-level same-organization ownership validation can be bypassed by privileged raw SQL;
  database/RLS administration remains trusted.

## Required security tests

- Cross-tenant/membership-role/disabled-org/anonymous/CSRF/method denial.
- Foreign consumer and foreign/sibling token non-disclosure.
- Plaintext/hash absence from persistence, audit, session, messages, GET, failures, and captured logs.
- Audit-failure rollback for issue, rotation, and revocation.
- Concurrent or repeated rotation/revocation behavior and revoked-token gateway/MCP denial.
- Generated-subject collision/exhaustion and forged-subject rejection.
- Migration preservation/backfill/reverse/re-forward and protected membership deletion.
- PostgreSQL non-owner FORCE-RLS checks for project ownership and token lifecycle.
