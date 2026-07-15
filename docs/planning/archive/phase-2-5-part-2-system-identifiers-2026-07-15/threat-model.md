# Threat Model: phase-2-5-part-2-system-identifiers

## Assets

- Tenant-scoped organization, project, scenario, document, document-set, and consumer metadata.
- Stable GitOps identifiers, scenario aliases, release manifests, storage keys, and audit lineage.
- Authorization decisions, PostgreSQL tenant context, and RLS isolation.

## Actors

- Anonymous visitor and unauthenticated caller.
- Authenticated operator with one or multiple organization memberships.
- Platform administrator.
- Malicious or compromised tenant operator.
- GitOps/import and management-command operator.

## Entry points

- Covered console create forms and success redirects.
- Canonical UUID and legacy integer console detail/action URLs.
- Model/service creation paths, GitOps imports, seed commands, and migrations.
- Path parameters, forged POST fields, names, titles, filenames, and aliases.

## Trust boundaries

- Browser input to Django forms/services.
- Session identity to membership/action authorization.
- URL locator to membership-scoped object resolution and singleton tenant context.
- Application allocation/retry logic to database uniqueness constraints.
- Schema/data migration to existing durable identifiers and references.
- GitOps explicit identifiers to trusted declarative import validation.

## Data classifications

- Names, slugs, logical IDs, aliases, UUIDs, subjects, and relationships: internal tenant metadata.
- Original filenames and document titles: potentially sensitive tenant metadata.
- Document bytes, prompt bodies, credentials, and token plaintext: restricted; Part 2 must not log,
  copy, or expose them.

## Authentication

Unchanged. Console session authentication, consumer bearer authentication, and token lifecycle are
outside Part 2. A public UUID is never an authentication credential.

## Authorization

Possession or knowledge of a UUID, slug, logical ID, alias, or legacy integer grants nothing.
Resolvers scope by authenticated membership/platform-admin policy before returning a target, then
re-run the existing action predicate. Disabled-organization write denial remains server-side.

## Tenant isolation

Both canonical and legacy locators resolve only inside authorized organizations. The resolved
trusted organization installs the transaction-local singleton tenant scope before related queries.
Wrong-tenant and nonexistent locators return an indistinguishable result. RLS remains defense in
depth and must be exercised under the non-owner application role.

## External systems

None. Identifier generation uses local standard-library cryptography and database constraints; no
dependency, network call, secret store, or production system is added.

## Abuse cases

- Enumerate UUIDs, slugs, or integer IDs and compare status/body/timing.
- Forge hidden or removed slug/logical-ID/alias fields in POST data.
- Trigger repeated collisions to consume CPU/database work.
- Use a legacy route to bypass authorization, CSRF, method, audit, or disabled-tenant checks.
- Supply names that normalize to empty, exceed limits, contain path-like text, or collide after
  truncation.
- Cause filenames/content-derived text to enter identifiers, logs, metrics, or object paths.
- Treat a GitOps explicit-ID exception as permission for ordinary console callers.

## Failure cases

- UUID data migration leaves null/duplicate rows or partially backfills across apps.
- Route switch lands before backfill or creates broken reverse lookups.
- Scenario row commits without its initial alias after allocation failure.
- Random suffix is truncated away or collision retries are unbounded.
- Rename silently changes a stable URL, manifest reference, or storage key.
- Legacy POST redirect changes method/body or drops CSRF/audit behavior.
- Superuser testing masks non-owner RLS or tenant-scope defects.

## Logging and audit risks

- Generated IDs and UUIDs create high-cardinality or tenant-identifying labels.
- Original filename/name may be logged during validation failure.
- Migration progress logging may expose row content.
- Switching target references may break audit correlation or rewrite historical evidence.

## Mitigations

- Cryptographic bounded suffix generation plus database uniqueness and bounded retry.
- Normalize/truncate before appending entropy; safe fallback prefix for empty results.
- Atomic domain services for creation and scenario-alias insertion.
- Membership-scoped dual-locator resolvers with identical permission and response behavior.
- Legacy unsafe routes execute the same handler rather than redirecting request bodies.
- Expand/backfill/constrain migration with null/duplicate assertions and resumable batches.
- Preserve existing IDs/references and keep GitOps explicit-ID validation isolated from console input.
- Stable content-free error codes, safe audit metadata, and low-cardinality route/outcome metrics.
- Independent PostgreSQL non-owner, migration, AppSec, and compatibility review.

## Residual risks

- Authorized users can see identifiers for objects they may access; browser history and copied URLs
  retain them by design.
- UUIDs reduce predictability but do not eliminate enumeration via other leaked metadata.
- Legacy integer routes remain an additional maintained attack surface during the compatibility
  window.
- Artifact/release integer locators remain until their Part 6 contract review, though they remain
  scoped non-authority locators.

## Required security tests

- Anonymous, wrong-role, disabled-tenant, membership-less, wrong-tenant, malformed, missing, and
  platform-admin cases across UUID and legacy routes.
- Response equivalence for foreign and nonexistent targets; no foreign names/counts/links.
- Forged technical form fields, normalization edge cases, collision exhaustion, concurrent create,
  and atomic rollback.
- CSRF, HTTP-method, audit action/outcome, redaction, and disabled-write parity on legacy/canonical
  action routes.
- PostgreSQL non-owner singleton/wrong/empty tenant scope and pooled-connection reset.
- Migration null/duplicate/preservation checks and GitOps/manifests/storage/token regression tests.
