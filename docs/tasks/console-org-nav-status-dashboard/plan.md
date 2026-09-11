# Task Plan: console-org-nav-status-dashboard

## Task summary

Improve the operator console's information architecture around two owner-requested
changes:

1. **Organization-scoped navigation.** Today the sidebar ([`apps/console/templates/console/base.html`](../../../apps/console/templates/console/base.html))
   is a flat list of object types (Organizations, Projects, Scenarios, Documents,
   Runs, …). Because every object in the domain graph is owned by an organization,
   the organization should become a persistent **selector (dropdown)** at the top of
   the chrome. Once an organization is active, the remaining navigation and its list
   screens are pre-filtered to that organization, so the operator stops re-choosing
   the tenant on every screen.

2. **Operational status landing dashboard.** The current landing page
   ([`apps/console/templates/console/dashboard.html`](../../../apps/console/templates/console/dashboard.html))
   only shows record counts. Replace it with an "is anything running / stopped /
   failing right now?" overview scoped to the active organization: live vs. terminal
   run buckets, pending approvals and human tasks, release/serving health, ingestion
   & index build state, and the agent-runtime kill-switch state.

Both changes are **presentation/navigation only**. The server continues to
re-authorize and re-scope every query from `allowed_organization_ids`; the session's
active organization is a *convenience filter*, never an authorization input.

Alongside these, the task carries a set of owner-requested UX-clarity fixes uncovered
in the console review (Scopes D–H): role-based action visibility so read-only roles stop
hitting `PermissionDenied` dead-ends; row-level "click to open"; document-set list/detail
simplification (drop the advanced card, show only the current version, make the lifecycle
list actionable); document chunk visibility for authorized users; and filterable run
monitoring. All remain presentation-layer changes over existing, already-authorized data
with no schema change.

## Background

- Tenant scoping is derived server-side everywhere from
  [`allowed_organization_ids`](../../../apps/tenancy/services.py) and the
  [`apps/console/scoping.py`](../../../apps/console/scoping.py) helpers. A user may be
  a member of several organizations; a platform admin sees all.
- Phase 2.5 Part 1 delivered the per-organization workspace (the organization detail
  page and cross-linked details) but **no persistent active-organization context** in
  the chrome — the sidebar and list screens still show every tenant the user can see,
  mixed together, with the organization chosen anew per screen.
- The UX review (this task's motivation) found the flat nav mirrors DB tables rather
  than the operator's mental model, and the dashboard answers "how many records
  exist" instead of "what needs my attention".
- Role-honest action visibility was originally tracked separately, then explicitly added
  to this task as Scope D so read-only users do not reach `PermissionDenied` dead-ends.
  Backend authorization remains authoritative.

## Scope

### A. Active-organization context and selector

- Add an **active organization** notion stored in the session
  (`request.session["active_organization_id"]`), resolved and validated **on every
  request** against `allowed_organization_ids(user)`:
  - If the stored id is missing, invalid, or no longer permitted → clear it and fall
    back to a default (single membership → that org; multiple → an explicit
    "All organizations" / none-selected state; platform admin defaults to
    "All organizations").
  - Never trust the session value for authorization; it only narrows an
    already-tenant-scoped queryset.
- Add a **context processor** (`apps/console/context.py`, registered in
  `TEMPLATES.OPTIONS.context_processors`) that injects, for authenticated console
  users on every template: `active_organization`, `available_organizations` (bounded,
  ordered, from `scoped_organizations`), and `workspace_multi_org`. Views continue to
  compute operation-specific capability decisions through the existing authorization
  services; the context processor does not duplicate those decisions.
- Add a small **switch-organization** endpoint (`POST /console/switch-organization/`,
  CSRF-protected, login-required) that validates the requested id against
  `allowed_organization_ids` and updates the session, then redirects back (safe,
  same-origin `next`). Rejects non-member ids with 403 (no enumeration signal).
- Render the selector in the sidebar:
  - Multiple organizations → a `<form>`-backed `<select>` (progressive-enhancement:
    works without JS; submits to the switch endpoint). Include an
    "All organizations" option only for users allowed to see more than one.
  - Single organization → a static label (no dropdown).
  - Platform admin → same control, "All organizations" default.

### B. Organization-filtered navigation and lists

- The sidebar's object links (Projects, Scenarios, Document sets, Runs, Consumers, …)
  carry the active organization so their list screens open pre-filtered.
- Each affected list view narrows its already-scoped queryset by
  `active_organization_id` **when one is selected**, in addition to (never instead of)
  the tenant scope filter. "All organizations" preserves today's behavior.
- List screens show the active-organization context (breadcrumb/eyebrow) and a clear
  "Showing: <org> — change" affordance that reuses the selector.
- Keep deep-link/back-compat: existing integer and UUID public routes continue to work
  when authorized, independent of the active display filter. A GET deep-link does not
  mutate session state; only the explicit CSRF-protected switch POST changes the active
  organization.

### C. Operational status dashboard (landing screen)

Replace the counts-only dashboard with an operational overview, scoped to the active
organization (or aggregated across all permitted orgs when "All organizations"):

- **Live vs. terminal runs.** Aggregate `AgentRun` and `WorkflowRun` by a small,
  bounded set of status buckets defined in the view (not free text):
  - *Running / active*: queued, running, `waiting_approval`, waiting (durable
    wait/human task).
  - *Needs attention*: failed, dead-lettered, awaiting recovery decision.
  - *Completed* (last N / last 24h): succeeded, cancelled.
  Show counts per bucket with links into the existing run list screens (filtered).
- **Pending human decisions**: open tool approvals
  ([`tool_approvals`](../../../apps/console/views.py)), workflow human tasks, and
  workflow recovery decisions the user is allowed to act on — the operator's queue.
- **Serving health**: scenarios with no active release; releases in `building`/failed
  eval; active canaries and their windows.
- **Ingestion & index state**: connector sources with failed/retrying last runs;
  document-set index builds in `building`/failed/`promotable`.
- **Runtime kill-switch banner**: if `AgentRuntimeControl` is suspended (global or for
  the active org), show a prominent banner with the reason and (for platform admins) a
  link to the control surface.
- All figures are **bounded aggregate queries** (counts + a small "latest N" list per
  card); no per-row fan-out, no N+1. Everything remains redacted (codes/counts only,
  consistent with existing run-detail redaction).
- Empty/first-run states: each card shows a "nothing here yet / create your first X"
  call to action instead of a blank panel.

### D. Role-based action visibility (from the UX review P0)

The nav and per-screen actions must reflect what the user may actually do; otherwise
read-only roles (`auditor`) and non-authors reach `PermissionDenied` dead-ends. The
create buttons are already gated (`can_create` hides "New scenario/organization"), but
several action affordances are **not** and must be:

- Sidebar sections/links are shown/dimmed based on the active-org capability booleans
  from the context processor (Scope A). Purely read-only users do not see authoring/
  operations entries they can never use.
- `scenario_detail`: gate **"Scenario Studio'yu aç"**, **"Grafikte aç"**, **"Yeni
  draft"** ([`scenario_detail.html`](../../../apps/console/templates/console/scenario_detail.html)
  lines 21, 47, 57–58) behind `can_author_scenarios`; today they render for everyone.
- `documents.html`: gate the connector/"Kaynakları yönet" and workspace-mutating
  entries by capability.
- Every remaining write `<form>`/button is audited against its view's authorization; if
  the user lacks it, hide it (or render disabled with a one-line "requires <role>"
  reason). The backend already re-authorizes — this is a dead-end-removal fix only.

### E. Row-level "click to open" and redundant action columns

Currently list rows expose a separate action link/button in an "İşlem" column and the
row itself is not clickable:

- [`scenarios.html`](../../../apps/console/templates/console/scenarios.html) — "Aç →"
  link in an İşlem column.
- [`documents.html`](../../../apps/console/templates/console/documents.html) — "Çalışma
  alanını aç" button in an İşlem column.
- The generic [`list.html`](../../../apps/console/templates/console/list.html) (used by
  organizations/projects/consumers/artifacts/releases) — only cell links.

Change: **the whole row opens the object on click**, for every openable object list, and
the redundant "İşlem/Aç" open-column is removed (row-scoped *write* actions such as
delete stay, but the plain "open" affordance moves to the row).
Accessibility is mandatory (progressive enhancement): keep a real `<a>` in the primary
cell so keyboard and screen-reader users and no-JS clients still navigate; add row
`cursor:pointer` + hover state + a JS click handler that ignores clicks on nested
interactive controls (buttons/links/inputs) and on text selection.

### F. Document-set list and detail simplification

- **Remove the bottom "Gelişmiş saklama yönetimi" card** from
  [`documents.html`](../../../apps/console/templates/console/documents.html) (lines
  20–25). The tombstone/purge capability is **not dropped**: physical purge stays an
  org-admin action surfaced from the document/document-set detail context where it is
  in scope, not as a catch-all card on the list page. (Confirm the standalone
  `advanced_document_inventory` route's remaining role.)
- **Show only the current set version expanded** in
  [`document_set_detail.html`](../../../apps/console/templates/console/document_set_detail.html)
  (today `{% for v in versions %}` renders *every* version with full member/index/job
  detail, lines 45–80). Older versions collapse behind a **"Geçmiş sürümler"** control
  (expandable section or dedicated route), keeping the working screen focused on the
  version the operator is actually editing/serving.
- **Turn the "Uçtan uca yaşam döngüsü" list into actionable steps** (line 19). Each step
  currently prints `label/detail/complete/next` as text. Where a step is incomplete and
  the user is authorized, render a **"yap" action** (button/deep-link) that performs or
  jumps to that step (publish draft, build index, promote index, bind scenario, grant
  consumer), instead of only describing the next action in prose.

### G. Document detail — chunk visibility (authorized only)

[`document_set_document_detail.html`](../../../apps/console/templates/console/document_set_document_detail.html)
shows document versions (parse status, mime, size) but no indexing outcome. Add, for
authorized users, **how the document was chunked**: per served/active index, the
**chunk count** and a **bounded preview of chunk text** for this document.

Data-model note: chunk text lives on the ingestion build side
(`IndexedDocument` → `Chunk`, scoped to an `IndexVersion`), not on the content-plane
`DocumentVersion`. The view must resolve content-plane document → `IndexedDocument`
within the relevant `IndexVersion` (by checksum/source URI) and read `Chunk.ordinal` +
`Chunk.text`. Because chunk text is retrievable corpus content, gate it by tenant + an
explicit capability (`can_write`/`can_admin_org`), bound the preview length and count,
and never expose embeddings.

### H. Filterable monitoring (runs)

The agent-run and workflow-run lists
([`agent_runs`](../../../apps/console/views.py) / `workflow_runs`) currently render a
fixed `order_by("-created_at")[:200]` with no filters. Add **server-side, bounded
filters**: status (using the dashboard buckets), scenario, organization (respecting the
active org), and a created-at range; add pagination for results beyond the cap. The
dashboard's "needs attention" cards deep-link here with pre-applied filter query params.

## Non-goals

- No change to authorization semantics, tenant isolation, or any public API/gateway
  contract. The active organization never widens access; hiding an action never grants
  one, and every hidden/disabled action is still re-authorized server-side.
- No new data model, migration, or production dependency. (Chunk visibility in Scope G
  reads existing ingestion tables; it adds no model.)
- No new runtime status computation for runs — reuse existing persisted statuses; only
  bucket/aggregate/filter them for display.
- No real-time/websocket updates; the dashboard is a request-time snapshot (optional
  manual refresh only).
- No change to the React Flow builder SPA.
- The tombstone/purge *capability* is not removed — only relocated out of the
  document-set list page (Scope F).

## Acceptance criteria

1. A persistent organization selector appears in the console chrome for authenticated
   users; switching organizations updates the session and is reflected across the
   sidebar and list screens without changing what the user is authorized to see.
2. The selector only offers organizations returned by `scoped_organizations`; a forged
   `active_organization_id` (non-member) is ignored/cleared server-side and returns 403
   from the switch endpoint, proven by test.
3. With an active organization selected, Projects/Scenarios/Document sets/Consumers/Runs
   list screens are filtered to it; "All organizations" reproduces current behavior.
4. Single-membership users see a static organization label (no dropdown); platform
   admins default to "All organizations".
5. The landing dashboard shows, for the active scope: live vs. needs-attention vs.
   completed run buckets, the pending-decision queue, serving/ingestion/index health,
   and a kill-switch banner when the runtime is suspended — each linking into the
   relevant existing screen.
6. Dashboard and nav queries are bounded aggregates (verified: no N+1; capped "latest
   N" lists) and contain no sensitive data (codes/counts only).
7. Read-only / non-author roles no longer see write/authoring affordances they cannot
   use (Scope D): `scenario_detail` Studio/draft actions, document-set connector/mutate
   actions, and sidebar authoring links are capability-gated; a forged request still
   fails closed server-side (proven by test).
8. Every openable object list opens the object on row click, with the redundant "open"
   action column removed, while keeping keyboard/screen-reader/no-JS navigation working
   (Scope E).
9. The document-set list no longer shows the bottom "advanced retention" card; the
   document-set detail shows only the current version expanded with a "Geçmiş sürümler"
   control for older ones; the lifecycle list renders an actionable "yap" control for
   each incomplete step the user is authorized to perform (Scope F).
10. The document detail shows chunk count and a bounded chunk-text preview per served
    index for authorized users only; unauthorized users see neither (Scope G, tested).
11. The agent-run and workflow-run lists are filterable by status/scenario/org/date with
    pagination; filters are enforced server-side within tenant scope (Scope H).
12. All existing console tests pass; new tests cover session validation, cross-tenant
    rejection, filtered lists, dashboard bucketing, action-visibility gating, row-open
    accessibility, current-version-only rendering, and chunk-visibility authorization.
13. Repository gates pass (ruff format/check, mypy, `manage.py check`,
    `makemigrations --check --dry-run` → no migration, pytest SQLite + affected
    PostgreSQL profile).

## Affected components

- `apps/console/base.html` (sidebar chrome + selector + role-gated nav; Scope A/D).
- `apps/console/dashboard.html` (rewrite to status overview) + new partial templates for
  cards.
- `apps/console/views.py` (`dashboard`, `switch_organization` [new], list views gaining
  active-org narrowing; `agent_runs`/`workflow_runs` filters + pagination [Scope H];
  `document_set_detail` current-version-only + actionable lifecycle [Scope F];
  `document_set_document_detail` chunk resolution [Scope G]; `documents` advanced-card
  removal [Scope F]).
- `apps/console/context.py` (new context processor) + `config/settings/base.py`
  (register it).
- `apps/console/urls.py` (switch-organization route; possibly a "past versions" route).
- `apps/console/scoping.py` (helper to narrow a scoped queryset by a validated active
  org id; run-list filter helpers).
- Templates: `scenarios.html`, `documents.html`, `list.html`, `document_set_detail.html`,
  `document_set_document_detail.html`, `scenario_detail.html`, `agent_runs.html`,
  `workflow_runs.html` (Scope D/E/F/G/H).
- `apps/console/static/console/` (small progressive-enhancement JS for row-open; CSS for
  hover/pointer and dashboard cards).
- Read-only reuse of `apps/agents`, `apps/workflows`, `apps/releases`, `apps/ingestion`
  (incl. `IndexedDocument`/`Chunk` for Scope G), `apps/tools`, `apps/observability`.

## Interfaces affected

- New internal console route `console:switch_organization` (operator UI only; not the
  consumer gateway; session/LDAP-auth, CSRF-enforced).
- New template context keys (`active_organization`, `available_organizations`, role
  booleans). No public/consumer API, event, or DSL change.

## Data impact

None. No model, field, index, or migration. Session gains one integer key
(`active_organization_id`) validated on read.

## Security impact

- The active organization is a **display filter only**. Every queryset still starts
  from `allowed_organization_ids`; the session value can only *narrow* it. A tampered
  session id resolves through the same membership check and is rejected/cleared.
- Switch endpoint is CSRF-protected, login-required, `POST`-only, validates membership,
  and uses a safe same-origin redirect (no open redirect).
- Dashboard aggregates reuse existing redaction (counts/codes only; no payloads,
  prompts, secrets, or cross-tenant rows). Kill-switch reason text is already
  operator-safe.
- **Chunk-text preview (Scope G)** is the one place this task surfaces corpus content.
  It is gated by tenant + an explicit write/admin capability, bounded in length and
  count, never includes embeddings, and is read from the tenant's own served index only.
- **Action visibility (Scope D)** is defense-in-depth for UX, never the access boundary:
  every hidden/disabled control is still re-authorized in its view. Hiding a control must
  not be relied on to prevent an action.

## Authorization impact

- No change to who can do what. Operation-specific views continue to compute the existing
  `can_admin_org` / `can_author_scenarios` / `can_manage_releases` / platform-admin
  decisions through `tenancy/services`; the context processor only supplies workspace state.
- The pending-decision queue on the dashboard lists only items the user is authorized
  to act on (reusing each feature's existing authorization query), and links do not
  imply the user may decide — the target view re-authorizes.

## Observability impact

- Optional: audit the organization switch as a low-severity console event
  (actor, from→to org id, request/trace id) consistent with existing
  `console.*` audit events. No sensitive data.
- No new metrics required; dashboard reads existing persisted state.

## Migration impact

None (no schema change). `makemigrations --check --dry-run` must report no changes.

## Dependencies

None new. Uses Django sessions (already enabled), existing scoping helpers, and
existing models. No frontend/npm change.

## Implementation steps

1. Add `resolve_active_organization(request)` + a queryset-narrowing helper in
   `scoping.py`/`context.py`, with strict validation against
   `allowed_organization_ids` and safe fallback.
2. Add the context processor and register it in settings; render the selector in
   `base.html` (progressive-enhancement form; single-org and platform-admin variants).
3. Add the `switch_organization` view + URL (POST, CSRF, membership-checked, safe
   redirect); optional audit event.
4. Narrow the affected list views by the active org when set; add the "Showing: <org>"
   affordance and org-carrying nav links.
5. Rewrite the `dashboard` view to compute bounded status buckets/aggregates and the
   pending-decision queue, plus kill-switch state; build the new dashboard template and
   card partials with empty states.
6. Add tests (below); run gates; update `dashboard`/navigation docs and this task's
   `verification.md`.

## Test plan

- **Session/context**: default resolution for single-org, multi-org, and platform
  admin; stale/invalid/non-member id is cleared and does not leak existence.
- **Authorization/tenant isolation**: switch to a non-member org → 403; with an active
  org set, list views never return other tenants' rows (the session cannot widen
  scope); CSRF/`GET` rejected on the switch endpoint.
- **Filtered lists**: with active org, each list is narrowed; "All organizations"
  matches pre-change output.
- **Dashboard**: run-status bucketing maps known statuses correctly (fixtures per
  bucket); pending-decision queue shows only authorized items; kill-switch banner
  renders when `AgentRuntimeControl` is suspended (global and per-org); empty states
  render with no data; queries are bounded (assert query count / no N+1).
- **Action visibility (Scope D)**: for each role (auditor, scenario_editor,
  release_manager, org_admin, platform_admin), assert the authoring/operations
  affordances render only when authorized, and that a direct POST from an unauthorized
  user still returns 403 (visibility never becomes the authorization boundary).
- **Row-open (Scope E)**: the primary-cell anchor is present and correct for every list;
  the row-open handler ignores nested control clicks; no-JS navigation still works.
- **Document-set detail (Scope F)**: only the current version renders expanded; older
  versions are reachable via the "Geçmiş sürümler" control; each incomplete lifecycle
  step renders its action only for authorized users; the advanced card is gone from the
  list page while purge/tombstone stays reachable for org admins.
- **Chunk visibility (Scope G)**: an authorized user sees chunk count + bounded preview
  for a document's served index; an unauthorized/cross-tenant user sees neither and gets
  no chunk rows; embeddings are never serialized; preview length/count are bounded.
- **Run filters (Scope H)**: status/scenario/org/date filters narrow within tenant scope
  only; pagination bounds the result set; an org filter cannot widen beyond
  `allowed_organization_ids`.
- **Repository gates**: `ruff format --check apps`, `ruff check apps`, `mypy apps`,
  `python manage.py check`, `makemigrations --check --dry-run` (no changes),
  `pytest` on SQLite and the affected-app PostgreSQL profile per
  [`manual-testing-guide.md` §0.1](../../manual-testing-guide.md).

## Rollout plan

Pure application change, no migration. Deploy behind normal release. Because the
active org falls back safely when unset, existing sessions/bookmarks keep working
(they simply start in "All organizations" or their sole org).

## Rollback plan

Revert the change set; no data or schema to unwind. Sessions carrying
`active_organization_id` are harmless after rollback (the key is ignored).

## Risks

- **Perceived scope narrowing**: a user with an active org might think data is missing.
  Mitigation: always show "Showing: <org> — change" and an explicit "All
  organizations" option.
- **Session/scope divergence**: an org the user loses access to mid-session. Mitigation:
  re-validate every request and clear on failure.
- **Query cost on the dashboard**: several aggregates per load. Mitigation: counts +
  capped "latest N"; assert bounded queries in tests; consider short per-request
  caching only if measured necessary (not in initial scope).

## Resolved decisions (owner, 2026-07-20)

- **"All organizations" is offered to every user who can see more than one
  organization** (not only platform admins).
- **Dashboard "completed" window is the last 24h** by default, with an "N more" link
  into the filtered run list.
- **The organization switch is not audited** (low value, would add noise). Session read
  validation and the existing per-action audit remain.

## Status

**Implemented and verified (2026-07-21; corrected 2026-07-22).** All scopes A–H landed in one
changeset per the owner decision. The correction aligns the single-organization default,
deep-link behavior, and context-processor contract with the implemented security model. Gates
green: ruff format/check, `mypy apps` (402 files), `manage.py check`,
`makemigrations --check` (no migration), `compileall`, `pytest` SQLite (966 passed / 37
PostgreSQL-only skips), and the affected PostgreSQL profile (console 138 passed incl. 19 new
UX tests; new vector-store chunk-preview test passed). Two pre-existing environmental
failures in the untouched `apps/ingestion/tests/test_job_lifecycle.py` (MinIO blob store +
non-owner FORCE-RLS role) are unrelated to this change. Evidence: `verification.md`.
Deferred/not done: dark theme; headless-browser drive of the row-click/switcher JS
(progressive enhancement, no-JS paths preserved).

## Completion criteria

Acceptance criteria met with recorded evidence in `verification.md`; navigation and
dashboard behavior are documented in this task record; no migration; gates
green on SQLite and the affected PostgreSQL profile; final diff reviewed for scope,
tenant isolation, authorization, privacy, and query bounds.
