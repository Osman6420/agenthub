# Task Plan: phase-2-p9-console-ux

## Task summary

Modernize the operator console as a Turkish-first, scenario-centred experience. Make the
organization → project → scenario hierarchy and the scenario → document set → consumer retrieval
relationship visible and operable without exposing the backend entity model as the primary
navigation.

## Background

WS1 delivered the governed document plane and safe server-side binding/grant services, but the
console still mirrors backend tables as English top-level pages. Binding and grant management is
available only from a document-set detail page, so an operator cannot understand a scenario's
effective retrieval scope in one place. The owner accepted these product directions on 2026-07-13:

1. Turkish-first UI; full i18n infrastructure is not the immediate priority.
2. Organization → project → scenario is the primary information hierarchy.
3. Bulk upload should be document-set-first; staged indexing may be automatic while promotion is
   manual or explicitly selectable.
4. Keep AgentHub's native gateway and plan a `/v1/responses` compatibility facade separately.

## Scope

- P9.1: Turkish console shell, scenario list/detail, and an understandable scenario/document-set/
  consumer relationship matrix with authorized bind, unbind, grant, and revoke actions.
- P9.2: document-set workspace, bulk upload, generated IDs/titles, ingestion/index lifecycle and
  actionable status/progress.
- P9.3: visual Confluence/generic-REST source, mapping, schedule and automation controls over the
  existing governed backend contracts.
- P9.4: scenario-centred artifact/DSL/release visibility and links to graph preview; coordinate the
  editable/AI-assisted boundary with WS3.
- P9.5: responsive/accessibility/terminology consistency pass and operator usability verification.

## Non-goals

- Personal end-user LDAP/OIDC/OBO authorization (WS4, last; must be discussed again).
- Making `user`/`group` document grants effective.
- AI scenario generation (WS3).
- Implementing `/v1/responses` in this task.
- Replacing server-side authorization with UI state.
- A new frontend/runtime dependency in P9.1.

## Acceptance criteria

- [x] P9.1: a scoped operator can open a scenario and see its organization, project, bound document
  sets, index/published-version readiness, and consumer retrieval grants in one screen.
- [x] P9.1: authorized authors can bind/unbind document sets and grant/revoke consumers from that
  scenario screen; non-authors are read-only.
- [x] P9.1: cross-tenant IDs are rejected/not found and cannot create or remove relationships.
- [x] P9.1: relationship mutations continue through audited domain services.
- [x] P9.1: the shell and new surface are Turkish-first and responsive at defined breakpoints.
- [x] P9.2 implemented: an author works from a document set, uploads at most 20 bounded files in one request,
  and receives generated stable logical IDs and filename-derived titles without entering metadata
  per file.
- [x] P9.2 implemented: bulk uploads update one draft candidate, preserve the latest published membership when
  opening a new draft, and replace an older draft membership when the same logical document is
  uploaded again.
- [x] P9.2 implemented: the workspace distinguishes uploaded content, draft/published set versions, staged
  index build state and the active index; it exposes explicit publish, stage and manual promotion
  actions with the existing role split.
- [x] P9.2 implemented: staged builds accept only active platform profiles granted to the set tenant, run on the
  ingestion queue with identifier-only resource references, and never promote automatically.
- [x] P9.2 implemented: bulk/build/promotion paths deny cross-tenant IDs and unauthorized roles and retain
  domain audit evidence.
- [x] P9.3: a scoped operator can see each Confluence/REST source attached to a document set,
  its safe profile/contract identity, schedule/automation state, latest bounded counters and run
  status without seeing destination, credential, source-input value or document-content fields.
- [x] P9.3: an author can create a Confluence source only from an exact set grant and can create an
  immutable REST contract/source only from an exact set grant plus a same-tenant contract; all
  mutations use the existing audited services.
- [x] P9.3: the REST mapping editor validates the closed contract and a bounded synthetic response
  without network egress, logging or rendering mapped content.
- [x] P9.3: an author can run a source now and configure a bounded interval with `draft_only` or
  `stage_only`; only a release manager can choose `promote_if_safe` and exact scenarios already
  bound to the source document set.
- [x] P9.3: run/schedule actions enqueue identifier-only payloads, reject cross-tenant/unauthorized
  IDs and keep profile destinations/secrets out of HTML, messages, logs and task payloads.
- [ ] P9.4–P9.5 criteria are refined before each increment begins.

## Affected components

- `apps.console` views, URLs, templates and tests.
- `apps.documents` membership services and `apps.ingestion` staged-build task/read model in P9.2.
- Existing `apps.ingestion` connector contracts/services/tasks plus safe preview helper in P9.3.
- Phase/master/current-behavior documentation.

## Interfaces affected

- Additive authenticated console routes under `/console/scenarios/`.
- Existing POST routes and public gateway contracts remain compatible.

## Data impact

P9.1–P9.3 add no schema. P9.2 writes ordinary document/version/set-membership and index-version
rows. P9.3 writes existing immutable contract/source, schedule/target and sync-run rows through
governed services.

## Security impact

The relationship and connector pages expose authorization topology, so every queryset must be
scoped before rendering. POSTed scenario, document-set, consumer, binding, grant, profile,
contract, source and schedule identifiers are untrusted. CSRF remains mandatory. Stored names and
titles rely on Django auto-escaping. Connector destination/auth/secret details remain platform-only.

## Authorization impact

Read access follows existing organization membership. Mutations require
`can_author_scenarios` in the scenario/document-set organization and revalidate same-tenant targets.
The UI is non-authoritative. Personal `user`/`group` grants remain inert.

## Observability impact

Existing binding/grant/connector service audit events remain the state-change authority. P9.3 adds
dispatch-failure audit and durable dead-letter state but no high-cardinality metrics; document and
synthetic content, credentials, input values and bearer tokens must not enter logs.

## Migration impact

None for P9.1–P9.3.

## Dependencies

No new production dependency for P9.1–P9.3. Later visual work must reuse the existing frontend stack or
pass the repository dependency approval gate.

## Implementation steps

1. Implement P9.1 scenario-centred detail/read model and scoped mutation routes.
2. Add Turkish-first navigation and relationship presentation without removing legacy routes.
3. Add positive, read-only, cross-tenant, invalid-target, audit and compatibility tests.
4. Verify P9.1 and update current-state docs/handoff.
5. Implement P9.2 as a document-set-first workspace: bounded bulk upload, draft upsert, lifecycle
   state, queued staged build and separately role-gated manual promotion.
6. Implement P9.3 as set-scoped connector source, closed REST mapping/preview, schedule/automation,
   run-now and safe-status controls over the existing audited backend.
7. Refine and implement P9.4 and P9.5 sequentially.

## Test plan

- Scenario detail happy path and empty/deny-by-default state.
- Organization member visibility and membership-less/cross-tenant 404.
- Author bind/unbind and grant/revoke with audit events.
- Auditor read-only and mutation denial.
- Cross-tenant and malformed target denial.
- Existing document-set relationship routes remain compatible.
- P9.2 filename/ID generation, duplicate batch IDs, file-count/individual/aggregate size bounds,
  MIME denial, draft baseline preservation and same-document replacement.
- P9.2 build-profile tenant scoping, author/release-manager separation, queue payload, failed build
  state and promotion denial.
- P9.3 safe read model/redaction, exact profile grant, contract/source validation, synthetic preview
  bounds/no-egress, schedule role split/target binding, run-now queue payload and cross-tenant denial.
- Formatter, linter, type check, Django check, migration drift and focused/full tests.

## Rollout plan

Additive routes/templates first. Retain current document-set pages and POST flows during WS2 so the
new scenario surface can be evaluated without removing the fallback.

## Rollback plan

Revert the additive console commit. No data migration is required; relationships created through
the new screen are ordinary audited domain rows and remain manageable from legacy pages.

## Risks

- A visually clear matrix may be mistaken for effective release state; distinguish configured
  bindings from release-pinned and active-index state.
- Grant changes affect retrieval immediately for already pinned sets; binding changes require
  release recompilation. The UI must explain this difference.
- Turkish-first text can drift across legacy pages until later increments finish the pass.

## Open questions

- P9.2 decision: uploads update a draft only. Publishing and staging are explicit operator actions;
  promotion is always a separate release-manager action. Connector schedules keep their existing
  selectable stage-only/promote-if-safe automation and are not changed by manual upload UX.
- Exact `/v1/responses` compatibility contract is a separate public-API task.
- Full localization framework/ownership is deferred until Turkish-first UX is coherent.

## Status

In progress — P9.1–P9.3 verified; P9.4–P9.5 planned.

## Completion criteria

Each increment must separately reach Implemented and Verified. The overall task is Completed only
after current-behavior documentation, full verification, final security/SRE review and master-plan
status updates are complete.
