# Task Plan: phase-2-8-part-1-console-information-architecture

## Task summary

Deliver the Phase 2.8 console information-architecture and UX foundation without changing stored
data, mutation authority or public gateway behavior. Replace backend-entity primary navigation with
an organization-scoped task model: **Ana Sayfa**, **Projeler**, **Dokümanlar**, **İstemciler** and
**Çalıştırmalar**. Scenarios live under their project; artifacts, releases, DSL graph and run
subtypes remain accessible from their owning context rather than the sidebar.

## Background

The console already has organization scoping, a status dashboard, project/scenario/document detail
views and governed artifact/release/run operations. The remaining shell still exposes many backend
catalogues as peer destinations. Long detail pages mix overview, authoring, release, document and
operations concerns; old list ordering starts with organization rather than the object the user is
trying to find; and the sticky sidebar can end in a white, unreadable area on long pages.

The owner approved these Part 1 decisions:

1. The visible hierarchy is organization → project → scenario.
2. Projects are primary navigation; scenarios are reached from projects, not a global menu item.
3. Detail pages use a compact summary plus task-oriented tabs.
4. Removed global list GET routes redirect to the new context; exact detail routes remain available.
5. The organization home prioritizes operational attention plus a compact organization summary, not
   a full inventory dump.

## Scope

- Replace the authenticated sidebar with Ana Sayfa, Projeler, Dokümanlar, İstemciler and
  Çalıştırmalar.
- Keep the organization selector above primary navigation and preserve server-derived authorization.
- Make `/console/` the selected organization's home without a separate “Genel Bakış” heading.
- Present compact organization identity/status, scenario/index health KPIs and recent work. Health
  KPI actions open dedicated authorized result lists containing the exact scenario, canary, index or
  build-job records; individual health records are not rendered on the home page.
- Make project detail the scenario-list entry point and use organization → project → scenario
  breadcrumbs on scenario pages.
- Introduce reusable server-rendered summary/header and accessible task-tab presentation for project,
  scenario and document-set detail views. Render only tabs backed by current behavior.
- Remove Artifact, Release, DSL Grafik, Agent Çalıştırmaları, Workflow İşleri and global Senaryolar
  from the sidebar while retaining contextual detail/action access.
- Redirect legacy GET list/organization-workspace entry points to the authorized new context. Do not
  redirect POST/action routes.
- Reorder project/document-set lists to show object name first and organization second; show scenario
  name first inside project context without redundant organization columns.
- Move username and Çıkış yap to the top-right user area and remove “oturum açık” copy.
- Fix the sidebar so its dark background and readable navigation persist for the viewport and long
  pages, with an independently scrollable navigation area where necessary.
- Add concise purpose/help text and actionable empty states; retain technical IDs as secondary
  operational information.
- Verify responsive, keyboard, focus, table and non-color status behavior at the accepted widths.

## Non-goals

- Creating or changing roles, including the proposed `document_manager` role.
- User/membership assignment UI or authentication/group-mapping changes.
- Question-set storage, retrieval evaluation, answer judging or quality percentages.
- New chunking/retrieval controls, BM25/vector/hybrid profile authoring, reranker selection or LLM
  document summaries.
- Automatic document-set publishing, index preparation/promotion or connector lifecycle changes.
- A new unified run persistence/read model or normalized cancellation semantics. The Çalıştırmalar
  landing may group/link existing authorized run views only.
- Kill-switch suspend/resume mutations or an expansion of kill-switch authority.
- Capability-oriented scenario-type redesign, new artifact-selection controls or release compiler
  changes.
- Removing exact artifact/release/run detail routes or changing state-changing route contracts.
- Public `/v1/chat/completions`, `/v1/responses`, MCP or other gateway contract changes.
- A new frontend or production dependency, data migration or production access.

## Acceptance criteria

- [x] The authenticated sidebar contains Ana Sayfa, Projeler, Dokümanlar, İstemciler and
      Çalıştırmalar,
      plus the organization selector; scenario/artifact/release/DSL/run-subtype links are absent.
- [x] Organization selection narrows presentation but cannot widen `allowed_organization_ids`, RLS
      scope or action authorization.
- [x] The organization home shows compact identity/status, health KPIs and recent work without
      individual health records; KPI actions open dedicated authorized exact-record result lists.
- [x] Project detail exposes its scenarios and scenario actions; scenarios are not presented as a
      primary global catalogue.
- [x] Scenario breadcrumbs consistently show organization → project → scenario, and the project
      link returns to the owning project's scenario context.
- [x] Project, scenario and document-set details share the approved summary + task-tab pattern and
      do not render empty placeholders for unimplemented Phase 2.8 features.
- [x] Legacy GET list/workspace routes redirect to an authorized contextual destination with safe
      filters preserved; canonical detail routes and all POST/action routes retain their current
      method, CSRF, authorization, audit and idempotency semantics.
- [x] Cross-tenant, inaccessible and malformed route/filter values fail without exposing foreign
      names, slugs, identifiers, counts or existence.
- [x] Lists show the sought object before organization; scenario tables inside a project show
      scenario name first and avoid redundant organization columns.
- [x] Username and Çıkış yap appear at top right; “oturum açık” is absent.
- [x] At 390, 900 and 1440 px, the sidebar remains readable on long pages, content/tables remain
      usable, focus is visible, tabs are keyboard-operable and statuses are not color-only.
- [x] No migration, new role, production dependency, public API change or new mutation authority is
      introduced.

## Affected components

- `apps.console` URLs, views/context helpers, templates, static CSS/JavaScript and tests.
- Existing authorized read models from catalog, documents, artifacts, releases, agents, workflows
  and ingestion; their persistence contracts remain unchanged.
- Phase 2.8 planning, current console documentation and manual testing guidance when behavior lands.

## Interfaces affected

- Presentation-only changes to authenticated `/console/` navigation and selected legacy GET routes.
- Exact object detail and state-changing routes remain canonical and compatible.
- Active-organization session state remains a filter derived from the user's allowed scope, never an
  authority-bearing interface.
- Task tabs may use server-rendered routes or safe query parameters; no new frontend dependency is
  authorized.

## Data impact

No schema or stored-data change. Pages continue to expose only existing safe metadata within the
authenticated user's organization scope. Document content, prompt bodies, tokens, secrets and raw
run input/output are not added to navigation or telemetry.

## Security impact

Legacy redirects and expanded contextual links create IDOR, open-redirect and metadata-enumeration
risks. Redirect targets must be internal named routes derived from trusted, already-scoped objects.
Untrusted organization/project/scenario IDs and filter values never select authorization scope.
See [`threat-model.md`](threat-model.md).

## Authorization impact

None intended. Read access remains organization membership or explicit platform-admin access.
Existing operation-specific predicates remain authoritative for writes. UI visibility is
role-honest but not an authorization control. Disabled organizations retain their established
read-only behavior.

## Observability impact

Pure page views and redirects do not create business-audit events. Existing state-changing audit
events remain unchanged. If redirect/error diagnostics are added, they use stable route/reason codes
and safe actor/organization references without raw query strings, names, content or secrets.

## Migration impact

None. `makemigrations --check --dry-run` must remain clean. Discovery of a necessary stored field
requires stopping, updating this plan and obtaining migration approval.

## Dependencies

- Existing console organization scoping, role predicates and transaction-local tenant context.
- Existing project/scenario/document-set relationships and exact artifact/release/run detail routes.
- Current CSS/JavaScript stack; no new production dependency.
- [`docs/planning/phase-2-8-plan.md`](../../phase-2-8-plan.md).

## Implementation steps

1. Capture the current route/sidebar/detail-page inventory and focused baseline test evidence.
2. Define a route-transition matrix covering every removed sidebar destination, contextual target,
   preserved detail/action route and safe-filter behavior.
3. Add failing navigation, redirect, cross-tenant and POST/action compatibility tests.
4. Refactor the authenticated shell and active-organization home without changing scoping helpers or
   mutation services.
5. Make project detail the scenario-list entry point and update scenario breadcrumbs/links.
6. Add reusable accessible summary/tab presentation and migrate project, scenario and document-set
   details only where current behavior has a real tab destination.
7. Reorder affected lists, add explanatory/empty-state copy and point health KPI actions to scoped,
   exact-record health result lists.
8. Move the user/logout controls and fix viewport/long-page sidebar behavior.
9. Run focused and full automated checks plus the 390/900/1440 px manual journey.
10. Update current-state/manual documentation, record evidence and perform staff-engineer, AppSec and
    SRE final-diff reviews.

## Test plan

- Sidebar/link assertions for member, multi-organization member, auditor, organization admin,
  platform admin, anonymous and membership-less users.
- Active-organization selection, invalid/forged organization, disabled organization and RLS scope
  preservation.
- Organization home attention/health links for healthy, empty, failing and stale-reference states.
- Project → scenario forward/reverse navigation, breadcrumbs, empty project and unauthorized
  scenario access.
- Exact GET redirect matrix, query/filter allowlist and redirect-loop/open-redirect denial.
- Route regression proving detail URLs and every touched unsafe-method route keep method, CSRF,
  authorization, audit and idempotency behavior.
- Cross-tenant HTML/Location-header checks for names, slugs, IDs, counts and existence leakage.
- Project/document-set/scenario table column order and accessible table names.
- Task-tab roles, selected state, keyboard focus order, skip link, row actions and non-color status
  text.
- Manual screenshots/journey at 390, 900 and 1440 px, including a page taller than the viewport and
  horizontally wide tables.
- Ruff format/lint, mypy, Django check, migration drift, focused console tests, full SQLite suite and
  applicable PostgreSQL/RLS tests using repository-standard commands captured at implementation.

## Rollout plan

1. Land the shell, route-transition and contextual-page changes together so no sidebar destination
   becomes a dead end.
2. Deploy through the normal non-production path and verify member, multi-organization, auditor and
   admin journeys under the non-owner PostgreSQL role.
3. Monitor bounded route-level 404/403/redirect-loop/server-error signals.
4. Obtain owner acceptance for Turkish terminology, hierarchy, responsive behavior and contextual
   artifact/release/run access before marking Verified.

## Rollback plan

Revert the Part 1 presentation/route commit as one application release. No data rollback is needed.
Exact detail and mutation handlers remain intact, so rollback restores the former navigation and
list pages. If a redirect causes unexpected denial, fail closed and roll back; do not widen tenant
scope or bypass role checks.

## Risks

- Redirecting familiar list routes can break bookmarks, filters or tests if the transition matrix is
  incomplete.
- Removing global scenario navigation can make cross-project discovery slower; the Projects page
  must make project selection and scenario counts understandable without creating a hidden global
  scenario catalogue.
- Tabs can hide operational state or create inaccessible interaction if semantics/focus are wrong.
- A cosmetic organization selector can be accidentally treated as authority during refactoring.
- Health links can leak foreign metadata or point to broad catalogues instead of the failing object.
- Large server-rendered templates/views may become harder to maintain; shared presentation helpers
  should be focused without unrelated refactoring.

## Open questions

None blocking. Part 1 deliberately leaves the data, authorization and operational decisions of
Parts 2–5 to their own approved task records.

## Status

**Verified and owner-accepted — 2026-07-22.** Automated, full-regression, PostgreSQL tenant-boundary
and live runtime checks pass. The owner accepted the authenticated console journey and requested
closure; the absence of retained per-width screenshots is recorded as residual evidence risk.

## Completion criteria

All acceptance criteria map to evidence in [`verification.md`](verification.md); applicable
formatter, linter, type, Django, migration, focused/full and PostgreSQL/RLS checks pass; current-state
documentation matches verified behavior; staff-engineer, AppSec and SRE reviews have no unresolved
critical/high finding; and the owner accepts the responsive Turkish navigation journey.
