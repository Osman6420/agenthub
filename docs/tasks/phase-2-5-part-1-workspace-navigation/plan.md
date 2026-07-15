# Task Plan: phase-2-5-part-1-workspace-navigation

## Task summary

Deliver the first Phase 2.5 product-coherence part: retain the Turkish operator dashboard at
`/console/`, add organization status/navigation there and provide an organization overview under
`/console/o/<organization-slug>/`, with organization-scoped inventories and navigable detail
relationships. Preserve the existing canonical domain list/detail/action URLs. Reconcile the
artifact/DSL authoring guide with this navigation model and make current behavior, Part 1 behavior
and later Phase 2.5 targets visibly distinct.

## Background

The current console mounts operational lists directly under `/console/`, scopes each queryset to
all organizations visible to the signed-in user and often renders organization labels beside rows.
Scenario and document-set pages already expose some relationships, but project, consumer and
release detail coverage is incomplete and many names are not links. The current PostgreSQL web
transaction receives the user's full allowed organization set; there is no organization overview
or single-target context contract.

Part 1 creates the navigation and tenant-context foundation before identifier generation, ownership
migration, credential management, document workflow redesign or new DSL execution. Those concerns
remain in later parts because they have separate schema, authentication or public-contract gates.

## Scope

### Dashboard, workspace entry and context

- Keep `/console/` as the dashboard. Add an organizations section listing only organizations the
  signed-in user may access, with name and active/disabled state. The organization name is the
  primary link to its organization overview.
- Dashboard totals and platform-wide widgets must either be explicitly defined as the authorized
  user's aggregate or visibly platform-wide for platform administrators; they must not look like
  active-organization values before an organization is selected.
- Add an organization overview rooted at `/console/o/<organization-slug>/`.
- Resolve the slug only through the authenticated user's allowed organizations. Return the same
  not-found response for a nonexistent slug and an inaccessible organization. An authorized
  disabled organization resolves to a visibly read-only overview; all operational mutations remain
  unavailable and fail server-side until it is active.
- Retain the resolved `Organization` model as the typed server-side context for the organization
  overview handler; do not derive authorization from a session value or hidden form. Existing
  object detail/action routes infer organization from the server-resolved target and display it
  visibly.
- On PostgreSQL, narrow `app.tenant_scope` to the single organization before organization-overview
  relationship queries and, on existing object routes, immediately after the target is resolved
  through the user's membership-scoped queryset. Aggregate dashboard/list pages retain only the
  minimum multi-organization scope required to show authorized rows.
- Show the relevant organization persistently on organization and object detail pages. Organization
  switching returns to the dashboard organization section; platform-admin cross-tenant access
  remains visibly privileged.

### Information architecture and routes

- The organization overview exposes its projects, scenarios, document sets, client applications,
  artifacts, releases and organization-scoped runs/operations.
- Platform-wide health/observability/administration stays outside `/console/o/<slug>/`; no tenant URL
  parameter is used to grant platform privileges.
- Preserve the existing canonical list, detail and action route names. Add only the organization
  overview route and the missing detail routes required by the relationship graph.
- Existing domain links continue to use their current URL shapes. A detail/action view resolves its
  target through the authenticated user's allowed scope, derives the organization from that trusted
  object and then narrows subsequent queries. There is no legacy redirect period and no unsafe
  method replay/redirect problem.
- Do not expose database primary keys as authorization. Existing integer detail identifiers may
  remain route locators in Part 1, but the object must resolve inside the user's authorized scope;
  the identifier itself grants nothing. Stable generated public identifiers are Part 2.

### Detail pages and relationship links

- Add or complete organization, project, scenario, document-set, client-application, artifact and
  release
  detail presentations needed for navigation.
- Organization overview shows organization information/status and its projects, scenarios,
  document sets, client applications, artifacts and releases. Every displayed name links to the
  corresponding detail page.
- Project detail lists only its scenarios; document sets and consumers remain organization-owned
  inventories and are not rendered as project children.
- Scenario detail links to its project, exact artifacts, releases, document sets and bound
  consumers.
- Document-set detail links to bound scenarios and consumers with effective grants.
- Consumer detail links to scenario bindings and effective document-set grants. Part 1 displays
  safe token metadata only if already available and adds no issue/rotate/revoke action.
- Artifact detail links to scenarios/releases pinning the exact version. Release detail links back
  to scenario, exact artifacts and rollback lineage where the data already exists.
- Every named object in these inventories and relationship sections uses its display name as the
  primary detail link. Internal IDs/checksums remain secondary operational diagnostics.
- Empty, unauthorized and stale relationships render without leaking a foreign object's name,
  count, identifier or existence.

### Documentation delivered with Part 1

- Update `docs/architecture/artifacts-and-dsl-authoring-guide.md` in the same implementation diff.
- Add an explicit contract-status legend that can identify `Current`, `Part 1`, `Later Phase 2.5`
  and `Phase 3` behavior without ambiguous future tense.
- Add the organization/project/scenario ownership graph and clarify that document sets, consumers
  and published artifacts are organization-owned reusable objects linked through scenarios.
- Add the detail-link/authoring-entry map: scenario studio is the contextual authoring entry point;
  artifact detail is immutable version inspection; release detail is exact runtime pin inspection.
- Keep transform/retrieval DSL examples labelled as unimplemented targets. Part 1 must not make the
  guide claim that target operations are accepted by current validators.
- Re-run a code-authority audit for every guide section touched and update its source-file links.

## Non-goals

- Generating or migrating slugs, logical IDs, scenario aliases or public IDs (Part 2).
- Replacing `AIProject.owner` with a membership/user foreign key (Part 3).
- Issuing, rotating or revoking consumer tokens; changing `Consumer.subject`; adding OIDC or mTLS
  authentication modes (Part 3).
- Redesigning document upload/version/index lifecycle (Part 4) or connector/source wizard (Part 5).
- Building the scenario studio (Part 6), implementing transform/retrieval DSL operations (Part 7),
  or adding public OpenAI-compatible endpoints (Part 8).
- Selecting reusable artifact versions while creating/editing a scenario draft is Part 6. Part 1
  only makes existing artifact/release relationships navigable.
- Responsive-width or keyboard/screen-reader manual acceptance, which remains waived by the owner.
- Production access, live egress, new dependencies or data migration.

## Acceptance criteria

1. `/console/` remains a dashboard and lists only authorized organizations with active/disabled
   state; clicking an organization name opens its workspace overview.
2. An authenticated member can enter only an organization to which they belong; forged,
   nonexistent and inaccessible organization slugs fail without disclosing which condition
   occurred. An authorized disabled organization opens in a visibly read-only state and cannot be
   mutated through direct requests.
3. A platform admin can select an organization through a visibly privileged path; ordinary users
   never receive an all-organization workspace.
4. Every organization-overview relation and target-object detail/action lookup is constrained to
   the trusted object's organization and retains its current role/action check. Aggregate dashboard
   and list pages expose only organizations/rows already authorized for the user.
5. PostgreSQL verification proves organization-overview and target-object requests narrow
   transaction-local RLS scope to one organization before related queries/mutations and reset on the
   next request/transaction; empty context remains fail-closed.
6. The organization overview shows its information and organization-owned inventories;
   organization → project → scenario and scenario ↔ document set ↔ client application navigation
   works in both directions. Project pages do not present document sets/client applications as
   children.
7. Scenario ↔ artifact ↔ release links resolve exact in-organization objects, and stale manifest
   references render safe diagnostics without linking across tenants.
8. Every displayed domain-object name covered by Part 1 links to its detail page; cross-tenant
   labels, counts and links do not appear in HTML or error messages.
9. Existing canonical list/detail/action URLs remain valid; the new organization overview adds no
   redirect migration, and current CSRF, authorization, audit and idempotency behavior is preserved.
10. Turkish navigation and relationship terminology is consistent in templates and the authoring
    guide; owner manual review covers the complete forward and reverse journey.
11. The artifact/DSL guide accurately labels current and planned contracts, documents the Part 1
    ownership/navigation model and passes a code-authority drift review.
12. No schema migration, credential operation, public gateway contract or live external call is
    introduced by Part 1.

## Affected components

- `apps/console/urls.py`, `views.py`, `scoping.py`, forms used by workspace screens and console
  templates/tests.
- `apps/tenancy/services.py`, request typing/context and the web transaction tenant-scope seam.
- Read models/relations from `apps/catalog`, `apps/documents`, `apps/identity`, `apps/artifacts`,
  `apps/releases`, `apps/agents` and `apps/ingestion`; their persistence contracts are unchanged.
- `config/urls.py` only if a clean platform/workspace URL split requires it.
- Phase 2.5 planning, authoring guide, current architecture docs and Part 1 evidence.

## Interfaces affected

- Operator console adds only the `/console/o/<slug>/` organization overview URL; existing canonical
  list/detail/action URL contracts remain valid.
- No gateway, MCP, GitOps or artifact JSON contract changes.
- Organization-overview scoping helpers receive an explicit organization. Existing target-object
  routes derive organization only from the authorized server-side object, never from an untrusted
  form/query value; subsequent relation queries must not silently widen to all memberships.

## Data impact

- Read-only navigation/query changes; no migration or stored-field change.
- Pages may expose existing safe metadata only inside the trusted relevant organization.
- Document content, prompt bodies, secrets, token plaintext and request/response content must not
  be added to navigation telemetry or audit payloads.

## Security impact

- This part changes the tenant-isolation execution path and therefore requires explicit owner
  approval before implementation, even though it intends to narrow access.
- The organization slug is untrusted routing input and cannot be treated as proof of membership.
- Relationship expansion increases IDOR and metadata-enumeration risk; every relation is filtered
  at the server and backed by singleton PostgreSQL tenant context.
- Existing links must not disclose foreign organization slugs or foreign object existence.

See [`threat-model.md`](threat-model.md).

## Authorization impact

- Authentication remains Django session authentication.
- Read authorization remains relevant organization membership or explicit platform-admin access.
- Existing action predicates (`can_admin_org`, `can_author_scenarios`,
  `can_manage_releases` and operation-specific checks) remain authoritative for writes.
- Active organization context narrows authorization; it does not add a role, grant or capability.
- A mismatch between route organization and target object returns not found before mutation.

## Observability impact

- Add content-free structured diagnostics for organization resolution failures only if the repository's
  existing security logging pattern supports them; use safe actor and organization references.
- Do not log raw URL query strings, object names, document/prompt content, consumer subjects or
  token material.
- Pure page views do not create business audit events. Existing state-changing audit events retain
  actor, action, target, authorization decision/outcome and trace correlation.
- Measure route/error volume only with low-cardinality route and stable reason codes.

## Migration impact

No database migration is planned. `makemigrations --check --dry-run` must remain clean. If
implementation discovers that a stored field/index is necessary, stop, update this plan and obtain
the migration/tenant-isolation approval before continuing.

## Dependencies

- P11 transaction-local tenant context and FORCE RLS implementation.
- Existing console role predicates and tenant-scoped query helpers.
- Existing scenario/document-set/consumer relations and release manifests.
- No new production dependency.

## Implementation steps

1. Capture baseline dashboard, route inventory, relationship matrix, console tests and PostgreSQL
   tenant-context behavior in `verification.md`.
2. Define a typed organization context/resolver and tests for member, non-member, platform admin,
   disabled organization and enumeration-resistant failures.
3. Define the dashboard organization section, the single new organization-overview route and the
   inventory of existing canonical routes that must remain unchanged.
4. Narrow PostgreSQL transaction-local scope before organization-overview relation queries and,
   for existing object routes, immediately after membership-scoped target resolution; prove scope
   cannot leak across requests or be widened by slug/form/query input.
5. Refactor organization/detail scoping helpers so related queries require the trusted organization;
   retain aggregate authorized lists and independent action authorization for mutations.
6. Update the dashboard organization section and organization/object headers while preserving
   existing domain link reverses.
7. Add missing project, consumer and release detail views; complete safe bidirectional links on
   scenario, document-set and artifact pages.
8. Add route-regression tests proving existing GET and unsafe-method URLs retain their method, CSRF,
   authorization, audit and idempotency semantics without redirects.
9. Update the authoring guide, Phase 2.5 plan and affected current-state architecture documentation;
   mark only behavior that tests prove as current.
10. Run focused and full checks, PostgreSQL isolation tests and Turkish manual journey review.
11. Review the final diff as staff engineer, AppSec and SRE; record evidence, residual risks and
    explicit owner acceptance.

## Test plan

### Unit and route tests

- Dashboard organization list and status/link behavior for member, multi-membership, platform admin,
  anonymous and membership-less users.
- Workspace resolver: authenticated member, multi-membership, platform admin, anonymous, no
  membership, authorized-disabled organization, inaccessible organization and malformed/nonexistent
  slug.
- URL reverse/resolve coverage for the organization overview and every existing canonical
  list/detail/action URL touched by the navigation work.
- Organization/detail relation scoping helpers refuse to default to all memberships after a trusted
  organization has been resolved.

### Authorization and tenant-isolation tests

- Inaccessible organization slug and foreign object primary key return 404.
- Foreign relationship names, counts and links are absent.
- Forged organization in path, query string, POST body and hidden fields cannot widen scope.
- Auditor may read but cannot mutate; author/admin/release-manager behavior remains operation
  specific; platform admin behavior is explicit.
- Cross-tenant POST/unsafe method does not mutate and produces no success audit event.
- PostgreSQL non-owner role verifies singleton `app.tenant_scope`, FORCE RLS denial and
  transaction-local reset. SQLite tests remain useful but are not accepted as RLS evidence.

### Relationship and compatibility tests

- Organization/project/scenario/document-set/consumer/artifact/release forward and reverse links.
- Exact artifact version/release pin links, stale/missing refs and empty states.
- Existing single-object/list GET and unsafe-method routes resolve without redirects and preserve
  their established behavior.
- Existing mutation audit events, CSRF protection and idempotency/retry behavior remain unchanged.

### Documentation and human review

- `git diff --check`, Markdown link targets and balanced fences.
- Guide claims sampled against listed validators/compilers/models/routes.
- Turkish manual journey: dashboard → organization → project → scenario → document set → client
  application, then reverse navigation plus artifact/release inspection.
- Responsive and assistive-technology manual acceptance is not required; existing automated
  accessibility checks must not be removed or weakened.

### Repository gates

- Ruff format/lint, mypy, Django check, migration-drift check, focused console/tenancy tests, full
  SQLite suite and applicable PostgreSQL suite using repository-standard commands captured from the
  live environment at implementation time.

## Rollout plan

1. Land Part 1 with the dashboard organization section, new organization-overview route, unchanged
   existing domain routes and no database migration.
2. Deploy application code through the normal non-production path; verify dashboard, one-member and
   multi-member journeys under the non-owner PostgreSQL application role.
3. Review 404/403 and server-error metrics using low-cardinality route labels.
4. Obtain Turkish owner acceptance for dashboard, organization overview and cross-link journeys.
5. Production deployment remains part of the separately approved Phase 2 closure; Part 1 planning
   authorizes no production action.

## Rollback plan

- Revert the organization-overview/template/scoping change as one application release; no data rollback
  is required.
- Existing canonical route handlers remain in place, so rollback only removes the new overview and
  related presentation/scoping changes.
- If singleton scope causes unexpected denial, fail closed and roll back application code; never
  widen RLS or bypass membership checks as a hotfix.
- Documentation status must be reverted with code so planned behavior is not presented as current.

## Risks

- Adding missing detail links can still create broken or cross-organization references if target
  scoping is inconsistent.
- Narrowing RLS after organization/target resolution may conflict with code that lazily queries
  another authorized organization; such queries are defects inside a single-organization request,
  not reasons to widen scope.
- Superuser behavior can hide non-owner RLS failures unless PostgreSQL tests explicitly use the
  dedicated application role.
- Inferring organization from a target object must happen through a membership-scoped lookup before
  any related metadata is rendered or mutation is authorized.
- New relationship pages can produce N+1 queries or high-cardinality telemetry.
- Documentation may drift if guide updates are postponed to a later DSL part.

## Resolved implementation decisions and open verification

- Part 1 uses **İstemci** / **İstemciler** in navigation because it covers both REST and MCP callers.
  `Consumer` remains the code/model/API term; **API Tüketicisi** is intentionally not used as the
  primary product label because it is narrower and more technical.
- Authorized disabled organizations remain visible for diagnostics and history with an explicit
  read-only state. All operational writes fail server-side, including platform-admin direct
  requests. Reactivation remains a separate platform lifecycle concern outside Part 1.
- Query-count budgets for the largest relationship pages should be set from representative local
  fixtures before implementation is marked verified.

## Status

Implemented and owner-accepted for progression on 2026-07-15; offline verification is complete,
while PostgreSQL non-owner verification remains an explicit Phase 2.5 closure carryover. The owner approved starting Part 1 on 2026-07-14
after confirming that existing canonical domain links remain unchanged. Implementation approval
includes the planned narrowing of transaction-local tenant scope for organization-overview and
trusted target-object requests; it does not authorize production access or any broader
authentication/authorization change.

## Completion criteria

- All acceptance criteria map to recorded automated or human evidence in `verification.md`.
- Applicable Definition of Done gates pass without weakened controls.
- Current-state documentation and the artifact/DSL guide match verified behavior.
- Staff-engineer, AppSec and SRE reviews record no unresolved critical/high issue.
- The owner accepts the Turkish journey and authorizes progression to Part 2.
