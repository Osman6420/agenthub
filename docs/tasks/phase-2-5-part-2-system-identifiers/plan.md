# Task Plan: phase-2-5-part-2-system-identifiers

## Task summary

Deliver Phase 2.5 Part 2: generate stable identifiers server-side for the
human-operated organization, project, scenario, document, and document-set creation
flows; add opaque public locators for tenant objects currently addressed by database
primary key; and preserve existing records, GitOps identifiers, gateway aliases, and
legacy console URLs through an additive compatibility migration.

## Background

Part 1 established the organization workspace and secure relationship navigation.
The current console still asks operators to supply `slug`, `logical_id`, and scenario
alias values, and most object routes expose integer primary keys as locators. Those
values do not grant authority, but they make ordinary creation depend on internal
architecture and make future URL compatibility harder.

The underlying fields are already durable contracts for GitOps, release manifests,
storage lineage, and gateway invocation. Part 2 therefore generates values for the
console rather than renaming existing values or replacing the declarative interfaces.
Authorization continues to derive from the authenticated actor, organization
membership, action predicate, same-tenant validation, and PostgreSQL RLS—not from any
old or new identifier.

## Scope

### Generated console identifiers

- Organization creation accepts display name and lifecycle status; generate the
  immutable organization slug server-side.
- Project creation accepts organization, display name, current owner input, risk and
  lifecycle settings; generate the project slug server-side.
- Scenario creation accepts project, display name, type, visibility, risk and status;
  generate both its internal slug and its first active API alias server-side.
- Generate the alias in the required `project-scenario-xxxx` shape, using normalized
  generated slugs, four cryptographically random lowercase base32 characters, and an
  organization-scoped collision check.
- Standalone document upload accepts organization, optional title and file; generate
  the document logical ID without embedding the original filename or content.
- Document-set creation accepts organization and display name; generate its logical
  ID server-side.
- Keep generated slugs/logical IDs within current field lengths and uniqueness scopes.
  Use a normalized human-readable prefix plus a collision-resistant random suffix,
  with a deterministic fallback prefix when Unicode normalization yields an empty
  slug.
- Bound collision retries and return a stable, content-free failure code if allocation
  cannot succeed. Database uniqueness remains the race-condition authority.

### Public locators and route compatibility

- Add immutable UUIDv4 `public_id` fields to `AIProject`, `Scenario`, `Document`,
  `DocumentSet`, and `Consumer`. New rows receive them automatically regardless of
  whether they originate from console, service, management command, or GitOps.
- Continue using the generated immutable organization slug for the organization
  workspace URL; do not add an unused second organization locator in this part.
- Make public UUID routes canonical for the affected console detail/action surfaces
  and update generated links/forms to use them.
- Retain legacy integer routes during the compatibility window. Safe detail GETs may
  redirect to the canonical UUID URL only after membership-scoped resolution. Unsafe
  methods must not rely on redirects: legacy POST routes call the same scoped handler,
  preserve CSRF/method semantics, and emit no foreign-object information.
- Preserve route names or provide explicit compatibility names so reverse lookups are
  migrated deliberately and existing external bookmarks/actions do not fail silently.
- Artifact and release locator redesign is not part of the identifier subset because
  their identifiers are governed by immutable artifact/release contracts and are
  reconciled with Scenario Studio in Part 6. Their integer locators remain non-authority
  until that review.

### Compatibility and immutability

- Preserve every existing slug, logical ID, scenario alias, consumer subject, release
  manifest reference, object-store key, audit record, and database primary key.
- Renaming a display name/title does not mutate its generated identifier or public ID.
- Keep explicit identifiers accepted by GitOps/import/service APIs for idempotent
  declarative workflows. Console requests cannot override generated values with forged
  POST fields.
- Centralize allocation in domain services/helpers called inside the creation
  transaction; do not rely on hidden form fields, client JavaScript, or templates.
- Keep scenario creation plus initial alias creation atomic and preserve its audit
  event. Allocation failure creates neither row.
- Record safe generated/public identifiers where operationally useful, but do not add
  UUIDs/slugs as high-cardinality metric labels or log original filenames/content.

### Creation-flow coherence

- Use Turkish labels and help text that describe business fields and explain that
  stable identifiers are generated automatically.
- Preserve organization-scoped form choices and server-side permission rechecks from
  Part 1.
- Redirect a successful creation to the new object's canonical detail/workspace page
  when one exists; do not strand the operator on an unrelated global list.
- Keep validation errors actionable without revealing whether a foreign-tenant
  identifier exists.
- Update the architecture/artifact authoring guide and current-behavior documentation
  with the console-versus-GitOps identifier contract and legacy-route window.

## Non-goals

- Durable project-owner foreign keys or membership lifecycle; Part 3 owns them.
- Consumer subject generation, token issue/rotation/revocation, OIDC, mTLS, or any
  authentication change; Part 3 owns the complete consumer credential contract.
- Removing explicit IDs from GitOps/import APIs or rewriting existing identifiers.
- Changing `/v1/query`, `/v1/invoke`, `scenario_alias`, release manifests, artifact
  references, storage keys, or runtime resolution.
- Removing legacy integer routes before compatibility evidence and an owner-approved
  deprecation decision.
- Artifact/release public-locator redesign, document-set-first UX, source wizard,
  Scenario Studio, DSL runtime, or OpenAI-compatible endpoints.
- Production deployment or live external egress.

## Acceptance criteria

1. Covered console forms contain no editable slug, logical-ID, or scenario-alias
   field, including when a forged POST supplies one.
2. Server-generated identifiers satisfy current length/uniqueness constraints for
   Turkish, ASCII, punctuation-only, duplicate, and maximum-length names.
3. Scenario creation atomically creates one collision-checked active alias in the
   `project-scenario-xxxx` form.
4. Existing records and explicit GitOps/import identifiers are byte-for-byte
   unchanged and remain resolvable/idempotent.
5. Project, scenario, document, document-set, and consumer rows have unique non-null
   UUID public IDs after forward migration and new writes receive one automatically.
6. Canonical console links use scoped UUID locators. Legacy integer GET/POST routes
   retain compatible behavior without turning either identifier into authority.
7. Rename/update operations do not change generated identifiers or public IDs.
8. Cross-tenant, malformed, nonexistent, and guessed identifiers have the same
   non-disclosing response behavior as Part 1.
9. Existing authorization, disabled-organization denial, CSRF, method restrictions,
   audit actions, RLS scope, and gateway/runtime behavior remain green.
10. The migration is additive, forward/backward tested on SQLite and PostgreSQL, and
    has a documented expand/rollback sequence.
11. Turkish creation journeys and post-create destinations receive owner review.
12. No dependency, credential, live egress, production, or destructive data change is
    introduced.

## Affected components

- `apps/tenancy`: organization creation service/helper and migration dependency.
- `apps/catalog`: project/scenario public IDs, identifier allocation, alias creation.
- `apps/documents`: document/document-set public IDs and logical-ID allocation.
- `apps/identity`: consumer public locator only; subject/token behavior unchanged.
- `apps/console`: forms, create handlers, scoped resolvers, URLs, templates, messages,
  and focused tests.
- GitOps/control-plane and seed commands: compatibility regression coverage.
- Architecture/current-behavior documentation and Phase 2.5 status records.

## Interfaces affected

- Operator-console forms and success redirects.
- Additive canonical UUID console URLs plus retained legacy integer console URLs.
- ORM schema gains internal `public_id` fields.
- No gateway, MCP, public JSON API, artifact schema, or GitOps contract change.

## Data impact

- Add one UUID per existing project, scenario, document, document set, and consumer.
- Existing business identifiers, references, content, secrets, and tenant lineage are
  not rewritten.
- UUIDs and generated slugs are internal metadata; document filenames/content remain
  restricted and are not included in opaque document logical IDs.

## Security impact

- Opaque public locators reduce accidental database-key disclosure but are defense in
  depth, not an authorization control.
- Random generation uses `secrets`, not `random`, and bounded allocation avoids
  attacker-controlled unbounded work.
- Foreign and missing identifiers remain indistinguishable after scoped lookup.
- No credential or authentication seam changes in Part 2.

## Authorization impact

All existing permission and tenant checks remain mandatory. Each resolver filters by
the actor's authorized organizations before resolving either UUID or legacy integer
locator, installs the trusted singleton tenant context, and then checks the requested
action. Generated values, URL possession, form origin, and redirects grant no access.

## Observability impact

- Preserve existing create/audit action names and authorization decision records.
- Audit target references may include the public UUID only after redaction/cardinality
  review; existing primary-key audit evidence is not rewritten.
- Metrics retain low-cardinality route templates and outcome/reason codes; never label
  by UUID, slug, logical ID, filename, or user-entered name.

## Migration impact

Use an expand-first additive sequence per affected app:

1. Add nullable, non-unique UUID columns without rewriting identifiers.
2. Backfill every existing row with a distinct UUID using a bounded, resumable data
   migration; assert no nulls or duplicates.
3. Alter each field to non-null, unique, immutable-at-the-model-boundary with a UUIDv4
   default for new rows.

Declare cross-app dependencies explicitly. Exercise forward, reverse, and re-forward
migration on representative existing data in SQLite and PostgreSQL. Application
rollback keeps the additive columns in place until the old version is restored; do not
drop populated columns as an emergency production rollback.

## Dependencies

No new package or production dependency. Use Python `uuid`, `secrets`, Django
`slugify`, database uniqueness, and existing transaction/services.

## Implementation steps

1. Capture a green baseline and inventory all console/service/GitOps creation paths,
   reverse lookups, model constraints, manifests, storage-key construction, and tests.
2. Add a small identifier-allocation module with bounded suffix generation,
   normalization, length handling, collision retry, and stable error codes.
3. Add public UUID fields through the expand/backfill/constrain migrations and verify
   existing-row preservation before changing routes.
4. Move console organization/project/scenario creation behind atomic domain services;
   generate slugs and the initial scenario alias server-side while retaining explicit
   GitOps paths.
5. Generate document/document-set logical IDs in their existing services; remove the
   corresponding editable console fields and ensure object-store keys remain opaque.
6. Add scoped UUID resolvers and canonical routes, retain legacy integer compatibility,
   then migrate templates/forms/reverse calls one surface at a time.
7. Update Turkish form labels, safe error handling, success destinations, audit target
   metadata, and documentation.
8. Run focused generation/migration/route/security tests, full repository gates, and
   independent staff-engineer/AppSec/SRE diff review.
9. Record PostgreSQL migration and non-owner RLS evidence before marking verified.

## Test plan

### Identifier allocation

- Turkish/ASCII/emoji/punctuation-only, whitespace, very long and duplicate names.
- Repeated mocked collisions, database-race `IntegrityError`, retry exhaustion, and
  transaction rollback.
- Exact scenario-alias shape, four-character entropy, organization uniqueness, and
  max-length truncation.
- Rename stability and rejection/ignoring of forged technical fields.

### Compatibility and routing

- Existing GitOps import remains idempotent with explicit identifiers.
- Existing aliases, manifests, object keys and token/consumer relationships are
  unchanged across migration.
- Canonical UUID GET/action routes, legacy integer GET compatibility, legacy POST
  method/CSRF behavior, malformed UUID, missing target and foreign target.
- Internal links/forms contain canonical UUIDs and no foreign identifiers.

### Authorization and tenant isolation

- Anonymous, membership-less, wrong-role, disabled-organization, cross-tenant, and
  platform-admin cases for every changed creation/resolver family.
- PostgreSQL non-owner FORCE-RLS tests for UUID and legacy resolution, singleton scope,
  wrong/empty scope, and transaction reuse.
- Successful and denied operations preserve redacted audit semantics.

### Migration and repository gates

- Existing-data forward/backward/re-forward migration with uniqueness/null assertions.
- Concurrent creation/collision behavior on PostgreSQL.
- Ruff format/lint, mypy, Django check, migration drift, focused tests, full SQLite and
  PostgreSQL suites, secret scan, diff check, and documentation link/fence checks.
- Turkish manual journey for each covered creation form and legacy bookmark behavior.

## Rollout plan

1. Land additive schema/backfill support while the old application remains compatible.
2. Deploy application code that writes public IDs and generated console identifiers,
   then switch generated console links to UUID routes while retaining integer routes.
3. Verify identifier allocation, legacy bookmarks/actions, authorization denials,
   audit outcomes, 404/403/5xx rates, and migration completeness in a non-production
   environment.
4. Production rollout remains part of the separately approved Phase 2 closure.

## Rollback plan

- Roll back application code to the prior version while retaining additive UUID
  columns and existing identifier values.
- Keep legacy routes available throughout rollback; do not widen authorization or RLS
  to restore access.
- If generated creation fails, disable the new creation UI and restore the previous
  application version; never accept client identifiers as an emergency bypass.
- Remove UUID columns only through a later reviewed cleanup after compatibility and
  retention requirements are satisfied, not during an incident.

## Risks

- A route resolver may look up a UUID globally before applying tenant scope and leak
  object existence.
- A naïve unique-default migration may duplicate UUIDs or lock large tables.
- Slug truncation may remove entropy or produce invalid/empty identifiers.
- Legacy and canonical routes may diverge in permission, CSRF, audit, or error behavior.
- Changing existing IDs would break GitOps, manifests, storage lineage, aliases, and
  operator bookmarks.
- Treating opaque UUIDs as authorization would recreate an IDOR vulnerability.
- Public UUIDs in logs/metrics could create sensitive high-cardinality telemetry.

## Open questions

- Confirm the compatibility-retention period before any future removal of legacy
  integer routes; removal is not authorized by this plan.
- Set the exact normalized suffix length/alphabet for non-alias identifiers during
  implementation review; it must meet field limits and measured collision risk.

## Status

Planned. The owner declared Part 1 finished and requested this plan on 2026-07-15.
Implementation has not started. The additive migration and console-route compatibility
design require explicit approval before code changes.

## Completion criteria

- Every acceptance criterion maps to evidence in `verification.md`.
- Applicable Definition of Done gates pass without weakened controls.
- Migration compatibility, authorization denials, PostgreSQL non-owner behavior,
  GitOps/runtime compatibility, and Turkish owner review are recorded.
- Staff-engineer, AppSec, and SRE final reviews have no unresolved critical/high issue.
- Parent Phase 2.5 and current-behavior documentation identify Part 2 as verified before
  progression to Part 3.
