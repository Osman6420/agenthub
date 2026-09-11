> Superseded: [tek aktif geliştirme görevi](../Agent_Hub_MD/plan.md). Bu belge tarihsel kaynaktır; bağımsız uygulanmaz.

# Task Plan: scenario-detail-ux-simplification

## Task summary

Simplify the scenario detail experience around the user's current state and next action. Replace
the permanent six-step setup checklist with a conditional first-time setup guide and a compact
post-release status/action surface. Move duplicated release, artifact, Studio-authoring and DSL
details to their existing authoritative destinations without changing release, authorization,
audit or runtime semantics.

## Background

The current scenario page mixes first-time setup, recurring publishing, operational controls,
integration guidance, release diagnostics and developer tooling. In a live 1280x720 review the
expanded Advanced block was approximately 3,616 px tall and the full page 5,539 px. At a 390x844
viewport those values were approximately 5,420 px and 8,737 px. An active scenario could
simultaneously show setup steps as waiting because the checklist inferred readiness from mutable
Studio records while the active immutable release remained valid.

The implementation brief is
[`implementation-instructions.md`](implementation-instructions.md). Security boundaries and
required negative tests are in [`threat-model.md`](threat-model.md).

## Scope

- Scenario detail information architecture and terminology.
- Conditional first-time setup guidance.
- Post-release current-state summary and one contextual primary action.
- Relocation or compaction of Advanced content.
- Consistent rendering for active, draft, candidate, failed-evaluation, disabled, legacy/imported
  and retrieval/non-retrieval scenarios.
- Role-honest controls and applicable automated/browser tests.
- User-guide and manual-test documentation updates.

## Non-goals

- Changing release compiler, evaluation, promotion, rollback, canary or activation semantics.
- Combining authoring and release-manager authority.
- Changing public API, consumer authentication, tenant isolation or document ACL behavior.
- Mutating immutable artifacts/releases or deleting historical records.
- Adding a production dependency or replacing Django templates/React Flow wholesale.
- Redesigning every console page.

## Acceptance criteria

- The permanent six-row checklist is no longer the primary experience for an already released
  scenario.
- First-time guidance contains at most four user-goal stages and is conditional on the compiled
  workflow's actual requirements.
- A retrieval source is required when the workflow requires retrieval and is not presented as a
  universal optional step.
- After first release, the page shows live release, draft divergence, evaluation, document readiness
  and consumer access as compact current state, not historical completion.
- Exactly one primary next action is selected from authoritative server state; secondary actions do
  not compete visually.
- Active release artifact pins live on release detail; scenario detail shows only a compact health
  summary and link.
- Release history has a clear dedicated destination; scenario detail shows only active and pending
  release summaries.
- Studio revision/publication state is merged into the flow/editing status and is not a duplicate
  card.
- Workflow DSL guidance is moved to Studio help/developer tooling and hidden from ordinary scenario
  operation.
- One-off testing and integration guidance are placed under explicit Test and Integration
  destinations rather than one oversized Advanced disclosure.
- Lifecycle and runtime suspension remain distinct governed actions but use plain-language labels
  and explanations.
- Legacy/imported scenarios with a valid active release never appear globally "unfinished" merely
  because no mutable Studio draft exists.
- Authorization, tenant scoping, CSRF, POST-only state changes, audit events and release gates are
  unchanged and covered by allow/deny tests.
- Desktop, mobile, keyboard and screen-reader semantics pass the mandatory browser gate.

## Affected components

- `apps/console/templates/console/scenario_detail.html`
- `apps/console/templates/console/release_detail.html`
- `apps/console/templates/console/builder.html`
- `apps/console/templates/console/base.html`
- `apps/console/static/console/console.js`
- `apps/console/views.py`
- Scenario/release/builder console tests and frontend tests where Studio help moves.
- `docs/user-guide.md` and `docs/manual-testing-guide.md`

The implementing agent must confirm exact references and current working-tree ownership before
editing; this list is navigation evidence, not authorization to overwrite existing changes.

## Interfaces affected

Operator-console presentation and navigation only. Preserve existing state-changing routes and
domain-service contracts unless the live code proves a small additive read model is necessary.
Public consumer APIs are unaffected.

## Data impact

No planned schema or persisted-data change. Existing draft, artifact, release, evaluation, document
and audit records remain authoritative and retained.

## Security impact

UI simplification must not turn presentation-derived readiness into authorization. The server must
continue to reauthorize every state change and enforce compiler/evaluation/index gates. Do not expose
artifact bodies, document content, secrets or hidden tenant identifiers in new summaries.

## Authorization impact

No policy change is approved. Scenario Editors may author/test; Scenario Release Managers may alter
served traffic; Runtime Operators may pause/resume; document content and document-set management
remain separately authorized. Hiding or disabling a control is not enforcement.

## Observability impact

No audit or metric removal. Existing lifecycle, publish, evaluation, promotion, activation,
rollback and runtime-control events must continue to be emitted by their current domain services.

## Migration impact

None expected. If implementation discovers a required model or migration change, stop, update this
plan and obtain the approval required by repository policy before proceeding.

## Dependencies

No new production dependency is approved or expected.

## Implementation steps

1. Reconcile this plan with the live working tree, active handoff, existing navigation work and
   current Compose/health state.
2. Build one authoritative scenario-page read model for first-time setup, current lifecycle state,
   blockers and the contextual primary action.
3. Replace the permanent checklist with conditional onboarding and released-state summary.
4. Remove/relocate duplicate Advanced content while retaining direct navigation to authoritative
   release and Studio details.
5. Correct navigation semantics: either implement real panels or present same-page links as section
   navigation; a link to Advanced must reveal its content if Advanced remains a disclosure.
6. Apply plain-language terminology and role-honest control visibility.
7. Add state-matrix, authorization, tenant-isolation, regression, accessibility and responsive tests.
8. Update user/manual documentation and record browser evidence.
9. Review the final diff as staff engineer, application-security engineer and SRE.

## Test plan

- Focused scenario setup/action/relationship/release console tests.
- Legacy/imported active release without a mutable Studio draft.
- Fresh scenarios for each supported preset and workflow requirement set.
- Clean draft, dirty draft, published workflow, candidate, failed eval, passing eval, active,
  disabled, superseded and rollback states.
- Scenario Editor, Release Manager, Runtime Operator, viewer, same-tenant unauthorized neighbor and
  cross-tenant user.
- CSRF and POST-only mutation checks.
- No secret/document-content leakage in summaries.
- Frontend type-check/tests/build if Studio UI changes.
- Repository formatter, linter, type-check, migration drift and applicable test suite.
- Mandatory live browser gate at desktop and mobile widths, including keyboard traversal and focus.

## Rollout plan

Ship as a presentation/read-model change over existing domain services. Verify current and legacy
records before deployment. No feature flag is required unless the final diff becomes too large for
safe atomic review.

## Rollback plan

Revert the presentation/read-model commit. Existing routes, releases, artifacts and lifecycle data
must remain compatible so UI rollback requires no data rollback.

## Risks

- A simplified CTA could imply authorization or bypass an existing gate if it calls the wrong route.
- Readiness may drift from compiler/runtime truth if reimplemented in templates.
- Hiding operational status may delay incident detection.
- Existing uncommitted navigation changes may overlap the same templates.
- Mixed legacy and current records may produce contradictory state unless explicitly modeled.

## Open questions

- Whether destinations should be separate server-rendered pages or true in-page panels; decide from
  current navigation work and browser evidence, not aesthetics alone.
- Whether completed first-time guidance disappears entirely or remains as a collapsed history/help
  link.
- The product-approved Turkish term set for release/artifact/runtime concepts.

## Status

Planned.

## Completion criteria

Map every acceptance criterion to evidence and satisfy the repository
[Definition of Done](../../ai/definition-of-done.md). Archive the task only after the mandatory
browser and authorization gates are recorded.
