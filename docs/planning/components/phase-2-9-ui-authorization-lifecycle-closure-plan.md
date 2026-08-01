# Phase 2.9 — UI, Authorization and Lifecycle Closure Plan

## Objective

Close the authorization disclosure, incomplete lifecycle transitions, unreachable operator
capabilities, setup gaps, and usability defects confirmed by the 2026-07-31 current-application
role/UI audit. The phase turns already implemented domain capabilities into a coherent,
deny-by-default browser experience without treating UI visibility as authorization.

## Owner or responsible area

Console/product experience, identity authorization, catalog/releases, documents/ingestion,
orchestration/runtime, and platform operations. Each part requires one task plan and one
verification record owned by the main implementation agent.

## Status

Planned. No product behavior is changed by this plan. Parts 1 and 2 are release-blocking; later
parts cannot be reported complete while either has an unresolved high-severity finding.

## Scope

- Repair exact-scenario runtime read/control authorization and the PostgreSQL non-owner RLS path.
- Make scenario activation and document/index promotion explicit, atomic, audited, and usable.
- Expose already supported release and runtime lifecycle controls to the exact responsible roles.
- Provide governed creation/provisioning paths for release artifacts and provider/connector setup.
- Make Studio AI authoring reliable and exact-responsibility aware.
- Remove confirmed navigation, feedback, content-access, language, and interaction-cost defects.
- Close reproducible test/type/format debt and automate the stable portion of the browser gate.

## Non-goals

- Weakening server-side authorization because a control is hidden in the UI.
- Allowing tenant-authored provider endpoints, secret values, TLS policy, or raw credentials.
- Automatically activating a scenario, release, document version, or index as a side effect of an
  unrelated create/publish/sync action.
- Expanding to production provider/connector egress, production data, personal MCP identity, or
  other Phase 3 scope.
- Replacing the mandatory human UX review with browser automation alone.

## Current state

The source evidence is the [role/UI audit report](../../tasks/current-application-role-ui-audit/report.md)
and its [verification record](../../tasks/current-application-role-ui-audit/verification.md). The
audit verified real Gemini chat/embedding profiles and most allow/deny journeys, but confirmed:

- a same-tenant, cross-scenario run disclosure for an exact-scenario runtime operator;
- a PostgreSQL non-owner RLS permission failure;
- UI-created scenarios that cannot become externally callable;
- index activation that leaves the served document-set version incomplete;
- unreachable release and runtime controls;
- missing governed authoring/provisioning surfaces;
- exact-scenario AI authoring permission mismatch and strict JSON integration failure;
- misleading/dead-end navigation, incomplete content-reader access, duplicate actions, weak dirty
  state feedback, mixed terminology, and high-click release assembly;
- three stale PostgreSQL workflow-wait tests, 22 mypy errors, and 11 Ruff-format deviations in the
  measured repository baseline.

## Target state

Every responsibility sees only its exact authorized objects and can complete its declared tasks
through reachable, comprehensible console journeys. Governed lifecycle transitions commit all
required state atomically or leave the prior state intact. The full post-development UI gate is
repeatable, evidence-backed, and blocks completion on functional or authorization regressions.

## Interfaces

- Operator console routes, forms, templates, React Studio, and navigation.
- Exact-scope authorization predicates for scenario, release, run, document set, and platform
  profile operations.
- Scenario/release/index lifecycle domain services and existing REST consumer behavior.
- Platform-managed model, embedding, and connector profile/grant administration.
- Audit events, run/release/index status surfaces, and task verification records.

Public API contracts should remain compatible. Any part that changes authentication,
authorization, tenant isolation, secret handling, or a public contract requires the explicit
approval mandated by `AGENTS.md` before implementation.

## Data flows

1. The authenticated actor and active organization resolve server-side responsibilities.
2. Exact object/action authorization scopes reads and mutations; foreign or out-of-scope objects
   remain non-disclosing.
3. Console commands call domain services rather than updating lifecycle fields directly.
4. Lifecycle services validate immutable pins and readiness, commit related pointers/state in one
   transaction, and emit a redacted audit outcome.
5. Provider/connector forms store only immutable platform profile metadata and secret references;
   runtime secrets remain environment/external-secret resolved.
6. Browser evidence records role, synthetic object identifiers, expected/actual result, request ID,
   and usability observations without tokens, prompts, provider output, or document bytes.

## Security boundaries

- The browser is untrusted and non-authoritative; hiding an action is not an authorization control.
- Organization scope is insufficient for exact project/scenario/document responsibilities.
- Cross-tenant and same-tenant cross-scope reads and mutations must fail closed, normally with a
  non-disclosing 404 where object existence is sensitive.
- PostgreSQL application roles remain non-owner, non-superuser, and `NOBYPASSRLS`; direct-table
  privileges must be least-privilege and verified with FORCE RLS enabled.
- Profile management never accepts or redisplays plaintext secrets and never gives tenant authors
  endpoint, redirect, TLS, DNS, or credential-policy control.
- Lifecycle and destructive actions require POST/CSRF, exact authorization, concurrency protection,
  confirmation where impact is material, and an audit outcome.

## Dependencies

- Phase 2.8 responsibility redesign and its exact-scope capability vocabulary.
- Existing scenario/release/run, document/index, provider-catalog, and audit domain services.
- Canonical PostgreSQL/pgvector/RLS test profile and local Compose stack.
- The mandatory post-development browser gate in the manual testing guide and Definition of Done.

Parts are dependency ordered. Parts 1 and 2 precede feature expansion. Part 3 depends on their
authorization/lifecycle contracts; Parts 4 and 5 depend on stable lifecycle targets; Part 6 follows
the stabilized journeys; Part 7 automates those final journeys and closes remaining quality debt.

## Milestones

### Part 1 — P0: exact-scope authorization and PostgreSQL containment

**Implemented and verified 2026-08-01.** Detailed task plan and evidence:
[Phase 2.9 Part 1 — exact run authorization and PostgreSQL containment](../archive/phase-2-9-part-1-exact-run-authorization-postgresql-containment-2026-08-01/plan.md),
[verification](../archive/phase-2-9-part-1-exact-run-authorization-postgresql-containment-2026-08-01/verification.md).

**Outcome:** an exact-scenario runtime operator cannot discover any other scenario's run, and the
same allow/deny result holds under the real non-owner PostgreSQL role.

- Intersect run list/detail/event/control queries with the actor's exact scenario responsibilities.
- Correct the least-privilege privilege/RLS path for
  `identity_platformresponsibilityassignment`; do not solve it with owner/superuser/BYPASSRLS.
- Update the three stale workflow wait tests to the current authorization contract and repair
  directly related typing errors.
- Add matched allow/deny tests for same-tenant cross-scenario, cross-tenant, unassigned, auditor,
  and exact runtime-operator identities at service, view, and PostgreSQL layers.
- Audit denied mutations without leaking run labels, actor data, event names, or payloads.

**Acceptance:** SQLite and PostgreSQL targeted/full applicable suites pass; direct URLs and browser
lists disclose only exact authorized runs; no broad database grant or client-trusted scope is added.

**Evidence:** complete. The unified and compatibility run surfaces now start from the canonical
authorized run queryset; hidden identifiers resolve to 404; persisted human-wait authority and the
non-owner PostgreSQL fixture are current. Full SQLite, full PostgreSQL and current-build browser
gates passed. Part 2 is the next release-blocking milestone.

### Part 2 — P0: callable-scenario and atomic served-index lifecycle

**Outcome:** a user can deliberately make a ready scenario callable, and an activated index is
immediately the exact index served by retrieval; partial success is impossible.

- Define governed scenario activate/disable transitions with readiness blockers, separation of
  duties, concurrency behavior, audit, and a reachable console action.
- Decide and document whether release promotion may offer an explicit combined activation command;
  it must never activate a draft implicitly.
- Make document-set-version activation, `built_index_version` linkage, index pointer promotion,
  and visible status one transactional domain operation with idempotent retry/reconciliation.
- Preserve the prior callable scenario/served index on failure and provide safe rollback.
- Prove UI-created scenario → release → eval → promote/activate → bound consumer invocation and
  upload → publish → build → promote → retrieval using synthetic data.

**Acceptance:** no audited bootstrap state edit is needed; consumer and retrieval paths work directly
after the documented UI transitions; injected failures leave no split lifecycle state.

### Part 3 — P1: exact-role release and runtime control surfaces

**Outcome:** release managers and scenario runtime operators can perform their declared actions from
reachable contextual pages, while every neighboring role is denied server-side.

- Restore a reachable release lifecycle page for eval, promote, rollback, start/stop canary, with
  blockers, current state, confirmation, and result feedback.
- Add exact-run cancel and exact-scenario pause/resume controls for scenario runtime operators.
- Keep organization/global administrator emergency controls distinct and visibly explained.
- Use POST/CSRF, idempotency/concurrency guards, exact object authorization, and audit for every
  mutation; do not expose controls merely because the navigation link is visible.

**Acceptance:** matched role pairs complete/deny each action in the browser and via direct POST;
unreachable/dead release routes are removed or redirect to an actionable contextual page.

### Part 4 — P1: governed setup and immutable release inputs

**Outcome:** authorized users can create every prerequisite needed for a valid release and an
administrator can safely provision platform profiles/grants without database/service bootstraps.

- Add guided authoring/versioning for input contracts, output contracts, and eval suites from the
  scenario/release journey, reusing canonical validators and immutable artifact services.
- Add platform-only model, embedding, and connector profile registration/disable plus explicit
  tenant grants; show capability/readiness metadata, never secret values or sensitive endpoints to
  tenant roles.
- Add connector source setup guidance and actionable empty states when no eligible profile/grant
  exists; egress remains disabled until all existing approval gates are satisfied.
- Keep initial Global Administrator and human directory-account creation as documented deployment/
  identity operations unless a separately approved threat model establishes a safe UI contract.

**Acceptance:** a fresh authorized synthetic tenant can reach release/profile/source readiness
without shell/database mutation; unauthorized, foreign-tenant, forged-parent, and secret-redaction
tests pass.

### Part 5 — P1: exact-permission AI authoring and provider response reliability

**Outcome:** an exact scenario editor can use Studio AI authoring, and supported provider responses
are converted to a validated non-publishing candidate reliably.

- Gate the AI panel on exact draft/scenario author permission, not organization-wide write state.
- Request provider JSON mode/schema where supported; otherwise add bounded, unambiguous safe fence
  normalization before the existing strict schema parser.
- Keep model output untrusted: canonical validation, size/token limits, no automatic draft publish,
  no authorization decisions from generated content, and no prompt/response logging.
- Provide actionable error categories and retry guidance without blind replay after unknown
  post-send outcomes.

**Acceptance:** exact editor allow and viewer/unassigned/foreign denial pass; raw, fenced, malformed,
oversized, timeout, and provider-error fixtures pass; one approved live synthetic Gemini smoke is
recorded without content or secret exposure.

### Part 6 — P2: navigation, comprehension, accessibility, and interaction cost

**Outcome:** every permitted task has one obvious entry point, truthful state, and bounded effort.

- Make navigation responsibility-aware while preserving direct-route server authorization.
- Correct Scenario Viewer Studio state, duplicate publish buttons, release dead ends, mixed language/
  timestamps, and local error-page guidance.
- Explain dirty manifest navigation blocking and provide save/discard/cancel choices.
- Add content-reader-safe preview/download with authorization, MIME/disposition, size, audit, and
  no-inline-active-content controls.
- Add release manifest presets/checklists and capability presets for consumers without weakening
  exact pin review.
- Verify keyboard use, visible focus, responsive layouts, error recovery, empty/loading states, and
  Turkish-first terminology. Set measured click targets: common create/publish tasks at most five
  primary actions; release assembly at most ten after choosing a preset; lifecycle actions at most
  three from scenario/set context.

**Acceptance:** the role matrix has no false affordance or unexplained dead end; critical journeys
meet the click targets or record an owner-approved exception with rationale.

### Part 7 — P2 quality closure: automated browser gate and clean repository baseline

**Outcome:** stabilized critical journeys run automatically, and human UX/authorization review
remains a mandatory completion gate.

- Add deterministic browser automation for login, responsibility-aware navigation, exact allow/
  deny, same-tenant cross-scope, cross-tenant, scenario callability, index retrieval, release/runtime
  controls, and provider-disabled empty/error states.
- Use synthetic seeded fixtures and stable selectors; capture screenshot, URL, role, request ID, and
  console/network failure evidence on test failure without secrets or content.
- Close remaining mypy and Ruff-format baseline deviations in owned files; do not mass-format or
  rewrite unrelated user changes.
- Run the manual post-development UX pass after automation, because click cost, clarity, misleading
  state, and keyboard usability are not fully proven by assertions.

**Acceptance:** repository-required SQLite/PostgreSQL/frontend/type/format checks pass; automated
critical journeys pass in CI or the documented staging-equivalent runner; manual evidence is linked
from each applicable task verification record.

## Risks

- Broadening run queries or database grants could hide rather than fix exact-scope authorization.
- Coupling scenario activation to release promotion can bypass intended governance.
- Multi-row index promotion can report success while retrieval still resolves an older/incomplete
  pointer unless one service owns the full transaction and reconciliation contract.
- Profile UI can create SSRF/secret-exposure paths if endpoint or credential policy becomes
  tenant-controlled.
- Preview/download can expose active content, cross-scope bytes, or unbounded storage reads.
- Click-count optimization can remove essential review/confirmation steps; safety gates take
  precedence over the targets.
- Browser tests can become flaky or leak evidence unless data, selectors, waits, and artifacts are
  bounded and redacted.

## Open decisions

- Whether scenario activation is a separate action or an explicit optional step within release
  promotion; implicit activation is excluded.
- Which profile fields are safe for organization administrators to see versus platform-only.
- Whether content preview is transformed safe text, forced download, or both by approved MIME.
- Which browser runner and staging-equivalent environment will be the CI authority for Part 7.

## Testing strategy

- Unit tests for lifecycle state machines, blockers, normalization, and exact capability rules.
- Service/integration tests for transactions, idempotency, audit, provider failures, and rollback.
- PostgreSQL non-owner FORCE RLS tests for exact-scope and cross-tenant allow/deny pairs.
- Browser tests for every responsibility affected by a part, including direct URL/POST probes,
  hidden/visible affordance parity, console/network errors, and responsive/keyboard behavior.
- Consumer API smoke after UI lifecycle transitions; real provider smoke only with approved
  synthetic data and environment-injected secrets.
- Full mandatory post-development gate from the manual testing guide with evidence in each part's
  `verification.md`.

## Observability requirements

- Stable redacted audit events for lifecycle, profile/grant, run control, content access, and denial
  outcomes with actor, tenant, exact target, decision reason, result, and request/trace ID.
- Metrics for lifecycle failures, provider candidate failures by safe category, reconciliation
  backlog, and browser-test failures without object content or secrets.
- Expected 4xx outcomes should remain diagnosable without full traceback noise or route-list/content
  disclosure in production-equivalent settings.

## Rollout

Deliver one task per part. Parts 1 and 2 use feature/state compatibility gates and staging-equivalent
PostgreSQL/browser evidence before later parts. New controls may be enabled per capability after
their exact-role matrix passes. Provider/connector setup remains deployment-disabled until the
existing endpoint, credential, privacy, cost, and rollback approvals are recorded.

## Rollback

- Authorization fixes roll back only to a deny-safe mode, never to the confirmed disclosure.
- Failed lifecycle rollout keeps the prior active scenario/release/index pointer and disables the
  new control until reconciled.
- UI routes may be hidden/disabled while domain behavior remains compatible; audit history and
  immutable versions are retained.
- Provider/connector profiles can be disabled and grants revoked without deleting lineage.
- Schema changes, if a part proves they are needed, require an additive migration and separately
  tested forward-fix/rollback strategy.

## Completion criteria

- All seven parts are implemented, verified, and linked to task evidence.
- Both high-severity authorization/lifecycle defects reproduce before and pass after the fix under
  the non-owner PostgreSQL profile and browser roles.
- Every declared responsibility has matched permitted and forbidden browser evidence, including
  same-tenant cross-scope and cross-tenant probes.
- UI-created synthetic scenario and document-set journeys require no database/shell bootstrap.
- Repository-required checks and the mandatory post-development UI gate pass; any skipped check is
  an explicit unresolved risk, not a pass.
- Current-behavior docs are updated only after implementation; durable authorization/lifecycle
  decisions receive ADRs where required.
- Staff-engineering, application-security, SRE, accessibility, and owner UX reviews are recorded.

## Links

- [Audit report](../../tasks/current-application-role-ui-audit/report.md)
- [Audit verification](../../tasks/current-application-role-ui-audit/verification.md)
- [Phase 2.8 plan](../phase-2-8-plan.md)
- [Manual testing guide](../../manual-testing-guide.md)
- [Testing rules](../../ai/testing-rules.md)
- [Definition of Done](../../ai/definition-of-done.md)
