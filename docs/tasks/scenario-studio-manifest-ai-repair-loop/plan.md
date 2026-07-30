# Task Plan: Scenario Studio manifest composition and AI repair loop

## Task summary

Make Scenario Studio the single scenario-development surface by moving exact candidate-manifest
composition out of the scenario overview, preserving an invalid manifest candidate in the editor,
returning safe structured canonical-compiler diagnostics, deriving manifest requirements from the
exact published workflow, and adding a human-triggered AI repair loop over transient workflow
candidates.

The delivery is split into two independently reviewable milestones:

1. **Studio manifest and diagnostics:** state-preserving exact manifest composition, canonical
   preflight, structured errors and candidate compilation in Studio.
2. **Dependency-aware and AI-assisted repair:** deterministic manifest requirement suggestions and
   iterative AI correction using freshly recomputed canonical diagnostics.

Neither milestone weakens publication, evaluation, promotion, tenant isolation, authorization or
immutable exact-version pinning.

## Background

The current scenario overview renders an exact artifact selector and posts its browser-only
selection to `scenario_compile_candidate`. If the release compiler raises `CompileError`, the view
discards the compiler reason, redirects to the scenario page and reconstructs an empty form.
Operators therefore lose their selected artifacts and roles and see only:

> Candidate release canonical compiler tarafından reddedildi.

This presentation also blurs two different contracts:

- workflow nodes are selected, configured, connected and validated inside Scenario Studio;
- an exact candidate manifest pins an immutable published workflow plus its immutable dependencies.

The existing Studio already provides graph/JSON editing, canonical workflow diagnostics, a managed
and custom-node catalog, transient AI candidates and explicit draft save/publish. The existing AI
planner is one-shot: it generates a candidate and returns diagnostics but cannot take the current
candidate and fresh diagnostics as feedback for a correction turn.

Phase 2.8 Part 4 introduced the dependent artifact selector and is automated/offline verified. This
task is a corrective follow-up; it must preserve Part 4's exact-version, tenant, role/type and audit
invariants while replacing the fragmented interaction.

## Locked product and architecture decisions

- Scenario Studio is the only primary surface for workflow authoring, node composition, canonical
  diagnostics, publication and candidate-manifest preparation.
- The scenario overview retains release status/history and a link into Studio; it does not retain a
  second editable manifest composer.
- Node composition and manifest composition remain explicit separate stages in the same Studio:
  nodes change a mutable workflow draft; manifest rows pin immutable published artifacts.
- A candidate release can reference only immutable `ArtifactVersion` records. An unsaved or merely
  saved workflow draft cannot be compiled into a release.
- Failed preflight or compile does not persist a `ScenarioRelease`, navigate away or clear the
  browser's bounded transient manifest state.
- The server recomputes canonical diagnostics. Client-supplied diagnostic text, required roles,
  tenant IDs, lineage, checksums and authorization claims are untrusted.
- Compiler failures are exposed through stable safe codes and bounded structured context such as
  manifest role, artifact type, node ID or JSON Pointer. Raw exception strings and provider errors
  are not a public contract.
- Dependency suggestions are deterministic assistance, not authority. Operators explicitly confirm
  exact versions; the final compiler re-resolves every pin and remains authoritative.
- AI repair is human-triggered one turn at a time. Each turn uses the current transient candidate,
  an optional bounded user instruction, a fresh server authoring context and freshly recomputed
  diagnostics.
- AI repair never automatically saves, publishes, compiles, evaluates, promotes, activates a
  Python node or invokes the candidate workflow.
- An autonomous multi-turn loop and a runtime-hosted authoring-agent scenario are deferred. After
  the human-triggered loop is verified, a separate spike/ADR may assess a platform-owned immutable
  system scenario with canonical diagnostics as its only bounded tool.

## Scope

### Milestone 1 — Studio manifest and structured diagnostics

- Add a scenario-locked Studio release panel alongside the existing draft/editor lifecycle.
- Move the typed `artifact type -> logical artifact -> exact version -> manifest role` composition
  interaction into Studio.
- Keep selection in React memory, mark it dirty and warn before destructive navigation/reload.
- Add an authenticated internal manifest-preflight endpoint that:
  - resolves the trusted scenario from the URL/server bootstrap;
  - requires exact scenario visibility and release-compile authority;
  - accepts at most 50 unique exact artifact-version IDs and closed role assignments;
  - re-resolves artifacts inside the scenario organization;
  - validates role/type compatibility, uniqueness, immutable checksum and canonical workflow/release
    constraints without creating a release;
  - returns a bounded structured diagnostic result.
- Add or adapt an authenticated internal candidate-compile endpoint that consumes the same request
  shape, repeats all authorization and validation under the write transaction, creates exactly one
  candidate release on success and returns its safe identifier/status.
- Preserve the current server-rendered POST route only as a compatibility shim if tests or callers
  prove it is still required. It must call the same application service; it must not remain a
  second business implementation.
- Define stable release diagnostic codes and an allowlisted safe serializer. Initial categories
  include:
  - missing or duplicate canonical workflow role;
  - duplicate manifest role or artifact version;
  - role/type mismatch;
  - artifact absent, foreign, stale or checksum-mismatched;
  - invalid immutable artifact body;
  - workflow compilation failure mapped to node/edge/JSON Pointer when available;
  - missing transform, tool-binding, verification-tool or child-workflow pin;
  - inactive/unregistered tool binding;
  - child-composition and document-set pin failures;
  - authorization, stale context and audit failures represented by their existing safe API policy.
- Render diagnostics inline at the affected manifest row and, where a node/edge identifier is
  present, reuse the Studio graph diagnostic highlighting.
- Record compile success and failure with stable redacted audit reasons. Preserve the existing
  fail-closed rule: a required audit persistence failure rolls back candidate creation.
- Remove the editable composer from the scenario overview after Studio parity tests pass.

### Milestone 2 — dependency-aware manifest and AI repair

- Add a read-only canonical release-requirements analyzer for an exact published
  `workflow_definition`.
- Derive requirements through the canonical compiler/compiled workflow contract rather than a
  client-maintained node-type table. The result identifies:
  - the exact root workflow pin;
  - required manifest roles and accepted artifact types;
  - roles already satisfied by the active/candidate release;
  - missing, incompatible, inactive or ambiguous roles;
  - exact candidate versions available to the authorized operator.
- Pre-populate only deterministic unambiguous suggestions. Ambiguous roles require explicit choice.
  Never resolve a moving `latest` reference during compile.
- Let the operator start from the active or selected candidate manifest, change one or more exact
  pins, add/remove dependencies and rerun preflight without leaving Studio.
- Demonstrate the intended graph journey: select two existing catalog node types, add/configure a
  different third node, validate, save, publish and prepare its exact candidate manifest.
- When a required capability is unavailable, preserve the existing `capability_missing` boundary:
  open only an unsaved governed custom/Python-node scaffold. The AI cannot create source, submit
  review, approve or activate it.
- Extend the AI authoring contract with a versioned repair operation. The request contains:
  - trusted scenario context from the route/server;
  - current transient workflow candidate within existing byte/depth limits;
  - optional bounded user correction instruction;
  - prior context/prompt contract metadata only for stale detection.
- Recompute diagnostics and a fresh bounded authoring-context snapshot before model egress. Do not
  trust diagnostic messages or context content supplied by the browser.
- Keep system contract, server context, canonical diagnostics, current candidate and untrusted user
  instruction in separate provider inputs.
- Require a strict structured response:
  - `workflow_candidate` containing a complete replacement candidate; or
  - `capability_missing` using the existing bounded suggestion contract.
- Validate output shape, depth, size, references, tenant scope and live capability status, then run
  canonical diagnostics before returning it to Studio.
- Show a per-turn summary containing safe diagnostic-code changes, not raw prompts/model reasoning.
  Replacing the current transient candidate remains an explicit user action when the model output
  regresses or changes unrelated nodes.
- Apply the existing AI rate limit, egress timeout, profile pinning, audit redaction and kill switch
  to repair turns.

## Non-goals

- Changing the workflow DSL, runtime semantics, public gateway API or release promotion criteria.
- Compiling a mutable draft directly into a candidate release.
- Persisting an invalid manifest draft, AI conversation history, chain-of-thought or model reasoning.
- Browser `localStorage`/`sessionStorage` recovery in the initial delivery.
- Automatic artifact creation, publication, evaluation, promotion or runtime invocation.
- Automatic Python/custom-node source generation, review, approval or activation.
- Letting the model choose tenant, scenario, artifact IDs, checksums, endpoints, credentials,
  model-profile IDs or authorization policy.
- A free-running/self-correcting server loop, multi-agent supervision or a user-owned authoring
  scenario in this task.
- Adding a production dependency, migration or public API contract.
- Replacing the canonical release compiler with a parallel frontend validator.

## Acceptance criteria

1. Scenario Studio shows the exact candidate-manifest composer for an authorized exact scenario;
   the scenario overview shows release summary/history and a Studio link but no editable duplicate.
2. An invalid manifest preflight returns safe structured diagnostics without creating a release,
   redirecting or clearing any selected artifact/version/role row.
3. A compile failure after preflight also preserves browser state and creates no partial release or
   workflow-version side effect.
4. Diagnostic codes are stable, bounded and safe; affected manifest roles and available
   node/edge/JSON Pointer locations are rendered inline. Raw exception/provider text is not exposed.
5. Preflight and compile re-resolve scenario lineage, exact artifacts, role/type compatibility,
   checksums, live tool/custom-node state and current authorization server-side.
6. Successful compile creates one immutable candidate, records required audit evidence and does not
   activate, evaluate or promote it.
7. Audit failure rolls back candidate creation; diagnostic/preflight reads do not create business
   audit records or durable authoring state.
8. Release requirements are derived from the exact published workflow through canonical
   server-owned logic. Suggestions never silently pick among ambiguous exact versions.
9. Operators can use two existing node types and one different/custom-capability path in a single
   Studio journey, then publish and prepare a matching exact manifest without visiting the scenario
   overview composer.
10. AI repair accepts the current transient candidate and a correction instruction, recomputes
    diagnostics/context server-side and returns a new transient candidate or bounded
    `capability_missing` result.
11. Every AI repair turn remains no-write until explicit draft save; it cannot publish, compile,
    evaluate, promote, activate or invoke.
12. Cross-tenant, forged ID/checksum/role, stale capability, unauthorized author versus release
    manager, CSRF, disabled organization and responsibility-expiry cases fail closed.
13. Prompts, user instructions, candidates, artifact bodies, schemas, provider errors and model
    reasoning are absent from application logs, audit payloads and metric labels.
14. Existing release-management CLI/services, exact manifest determinism, workflow diagnostics,
    AI candidate generation/acceptance and scenario lifecycle tests remain compatible.
15. Keyboard, screen-reader status/alert behavior, focus placement and responsive Studio layout are
    verified for successful, invalid, loading, stale and provider-failure states.

## Affected components

- `apps.releases`: structured compile diagnostics, canonical preflight/requirements service and
  candidate compile reuse.
- `apps.workflows`: location-aware workflow diagnostic projection; no DSL/runtime change.
- `apps.builder`: Studio bootstrap/API, transient manifest/AI repair orchestration, context refresh
  and safe response serialization.
- `apps.console`: scenario overview simplification, compatibility route and links.
- `apps.artifacts`, `apps.tools`, `apps.documents`: live exact-pin and capability revalidation.
- `frontend`: Studio release panel, manifest state, diagnostics mapping, AI correction interaction,
  dirty-state protection and accessibility.
- `apps.audit`/observability: stable redacted failure/success events and bounded metrics.
- Architecture/user/manual-testing documentation and focused tests.

## Interfaces affected

- New or versioned authenticated internal Studio JSON contracts for:
  - manifest options/requirements;
  - manifest preflight;
  - candidate compile;
  - AI candidate repair.
- Existing scenario/deep-link context remains server-owned.
- Existing server-rendered candidate POST may remain temporarily as a compatibility adapter.
- No consumer-facing gateway, MCP, OpenAI-compatible or public runtime contract changes.

If discovery requires a new public API, a production dependency, new persistent state, a migration
or an authorization model change beyond the already planned responsibility redesign, stop and
obtain explicit owner approval before implementation.

## Data impact

- Milestone 1 transient manifest selections live only in the current Studio page memory.
- Milestone 2 AI repair candidates remain transient until explicit existing draft save/update/copy.
- Successful candidate compilation creates the existing `ScenarioRelease` and compiler-owned
  immutable workflow records exactly as today.
- No new table, browser storage, conversation history or candidate body is planned.
- The UI must warn that a reload loses transient manifest and AI repair state.

## Security impact

- Canonical validation remains server-authoritative at preflight and mutation boundaries.
- All request fields use closed schemas, bounded counts/bytes/depth and unknown-field rejection.
- Structured diagnostics use safe codes/fields and never serialize arbitrary exception chains.
- AI output and diagnostics are untrusted inputs; live references and authorization are revalidated
  after every provider response and before every durable transition.
- Model egress retains governed profile pinning, timeout/size limits, context allowlists and secret,
  endpoint, source and document-content exclusion.

See [threat-model.md](threat-model.md).

## Authorization impact

This task does not authorize a role-model change. It must consume the central capability decision
owned by the planned responsibility-based authorization redesign:

- scenario authors/editors may edit, diagnose and test the exact scenario;
- exact `scenario_release_manager` authority is required to view release-only manifest options,
  preflight a release and compile a candidate;
- scenario visibility alone does not reveal release-only artifact options or grant compile;
- authoring authority does not imply release, approval, runtime-operation or document-content
  authority;
- all API/service/task entry points re-authorize against the trusted exact scenario.

Implementation sequencing:

1. Structured compiler diagnostics and pure preflight/requirements services may be developed before
   the authorization redesign.
2. The Studio API/UI must either land after the central capability decision is available or include
   an explicitly reviewed short-lived adapter with tests for both contracts. Do not introduce a new
   role check that must later be migrated.

## Observability impact

- Add stable bounded events/metrics for preflight outcome, compile outcome and AI repair outcome.
- Allowed dimensions: operation, safe diagnostic code, success/failure, artifact-count bucket,
  repair-turn outcome, context/prompt contract revision and request/trace correlation.
- Prohibited payloads: prompt/user instruction, candidate or artifact body, manifest descriptions,
  schema, raw exception/provider response, credentials/endpoints and model reasoning.
- Candidate compile remains a security/business mutation audit. Define and test audit persistence
  as fail-closed.
- Preflight/requirements reads may emit operational telemetry but do not create mutation audit rows.

## Migration impact

No schema or data migration is planned. A discovered need for persistent manifest/repair state,
compiler-diagnostic storage or new audit columns requires a plan update and explicit review before
implementation.

## Dependencies

- Canonical release compiler and workflow compiler contracts.
- Phase 2.8 Part 4 exact selector and scenario/Studio experience.
- Phase 2.6 Part 9 bounded authoring context and transient AI candidate lifecycle.
- Governed custom/Python-node catalog and capability-missing lifecycle.
- Planned responsibility-based authorization redesign for final Studio API capability checks.
- Existing release evaluation/promotion and audit rollback invariants.

## Implementation steps

### Milestone 0 — contract inventory and plan confirmation

1. Verify Codebase Memory index freshness when `index_status` is available; confirm graph candidates
   with Serena symbol/reference lookup, `rg`, direct code/test inspection and the live diff.
2. Inventory all callers of `compile_release`, `CompileError`, candidate compile routes,
   `can_manage_scenario_releases`/replacement capabilities, Studio bootstrap, artifact option APIs
   and AI generation/acceptance.
3. Inventory compiler error families and classify each as safe structured diagnostic, internal-only
   failure or authorization/not-found response.
4. Lock internal request/response schemas and Turkish-first UI state copy before implementation.
5. Update this plan/threat model if compiler side effects, compatibility callers or authorization
   sequencing contradict current assumptions.

### Milestone 1A — compiler/application services

1. Introduce typed internal diagnostic data (`code`, safe message key and allowlisted optional
   location/context) while preserving exception chaining for internal debugging only.
2. Refactor compiler checks to emit typed diagnostics without changing compile acceptance or
   canonical output.
3. Extract one application service that validates exact manifest selections, authorizes the exact
   scenario and supports:
   - no-write preflight;
   - transactional audited candidate creation.
4. Prove preflight leaves release/workflow-version state unchanged, including failure paths.
5. Add deterministic requirements analysis against an exact published workflow using shared
   canonical compilation/reference logic.

### Milestone 1B — Studio manifest UI

1. Extend server-owned Studio bootstrap with only safe release-panel capability/state metadata.
2. Add typed frontend API/types and the in-memory manifest composer.
3. Map structured diagnostics to manifest rows and existing graph/node/edge highlights.
4. Preserve selection on preflight/compile error; add dirty navigation/reload warning and explicit
   reset.
5. On success, show/link the exact candidate and refresh release summary without silently
   navigating away.
6. Remove the scenario overview composer after parity; retain release history and Studio link.
7. Keep any required legacy POST as a thin service adapter and document its removal trigger.

### Milestone 2A — dependency-aware journey

1. Preselect the exact just-published or explicitly selected workflow version.
2. Display required/satisfied/missing/ambiguous roles with exact provenance.
3. Offer active/candidate manifest pins as explicit starting templates, never as moving references.
4. Verify catalog node composition, custom-capability handoff, publish and candidate preparation as
   one end-to-end Studio journey.

### Milestone 2B — AI repair turn

1. Version the authoring provider contract for repair without weakening the existing generation
   union.
2. Add a repair service/API that rebuilds context and diagnostics, enforces rate/size/depth limits
   and sends separated trusted/untrusted inputs.
3. Validate the returned complete candidate, live references and canonical diagnostics.
4. Add “AI ile düzelt” with optional user instruction, safe loading/error states and explicit
   accept/reject of the returned replacement.
5. Preserve the current candidate when provider/parse/reference/diagnostic validation fails.
6. Verify audit/log redaction, provider timeout/rate-limit/outcome-unknown and kill-switch behavior.

### Milestone 3 — closure

1. Run focused and full repository checks and record evidence in `verification.md`.
2. Perform staff-engineer, AppSec and SRE review of the actual diff.
3. Run authenticated browser journeys for state preservation, accessibility and responsive layout.
4. Run an optional approved live-provider repair smoke; fake-provider tests remain authoritative CI
   evidence.
5. Update current architecture/user/manual-testing documentation.
6. Update master/Phase 2.8 status only after implementation and verification evidence exists.
7. Archive this task only after owner acceptance and planning-policy completion gates.

## Test plan

### Backend unit/integration

- Every structured diagnostic family maps to a stable safe code and allowlisted fields.
- Raw compiler/provider exception text is absent from JSON, HTML, logs and audit.
- Preflight success/failure creates no release, artifact, workflow version or audit mutation.
- Compile success creates exactly one candidate and no active release.
- Compile failure and audit failure roll back all new rows.
- Manifest count, uniqueness, unknown field, malformed ID, role/type, checksum and stale artifact
  boundaries.
- Missing transform/tool/verification/child-workflow roles and inactive tool/custom-node cases.
- Requirements analyzer parity with the final compiler across representative workflow node families.
- Existing CLI/service compiler callers and canonical checksums remain compatible.

### Authorization and tenant isolation

- Unauthenticated/CSRF failures.
- Scenario author can diagnose/edit but cannot access release-only options or compile.
- Exact scenario release manager can preflight/compile only that scenario.
- Sibling scenario/project, foreign tenant, forged artifact, disabled organization, revoked/expired
  membership/responsibility and stale assignment denial.
- List/options responses exclude unauthorized artifact metadata rather than returning disabled rows.
- Reauthorization after a responsibility/capability is revoked between options, preflight and
  compile.

### Frontend

- Selection survives preflight and compile errors.
- Removing/changing one pin retains unrelated rows.
- Inline manifest and graph diagnostics focus the affected item.
- Dirty navigation warning, explicit reset and successful candidate refresh.
- Requirements states: satisfied, missing, ambiguous, stale and unavailable.
- AI repair: success, regression/reject, invalid JSON, capability missing, timeout, rate limit,
  disabled profile, stale context and reference drift.
- Existing candidate generation/save/update/copy and graph/JSON parity regressions.
- Keyboard-only selection, focus recovery, screen-reader alert/status and responsive layout.

### Security/privacy

- Cross-tenant and identifier-tampering corpus.
- Prompt injection in current candidate, user instruction, diagnostics-adjacent catalog metadata and
  schema descriptions cannot change authority or provider contract.
- Candidate/context/schema/description/secret/source/document/endpoint exclusion from logs/audit.
- Request/candidate/context byte, depth, node, edge, artifact and turn-rate limits.
- AI generation and repair create zero durable rows until explicit save.
- Capability missing cannot persist source or activate/publish/release.

### Repository verification

- Focused PostgreSQL tests for releases, workflows, builder, console, tools and authorization.
- PostgreSQL non-owner/FORCE RLS suites affected by the final authorization implementation.
- Full pytest regression.
- Frontend typecheck, tests and production build.
- Formatter, linter, mypy, Django check, migration drift, compile/static checks and `git diff --check`.
- Browser journey using the repository manual-testing startup/health procedure.

## Rollout plan

1. Land typed diagnostics and shared application services behind existing behavior with compatibility
   tests.
2. Enable the Studio manifest panel only after exact authorization and parity tests pass.
3. Remove the scenario overview composer in the same reviewable milestone as Studio parity; retain a
   reversible link/compatibility adapter.
4. Enable AI repair under the existing AI authoring kill switch and approved immutable profile.
5. Keep AI repair unavailable with a safe actionable message when no approved provider/profile is
   configured.
6. Require owner browser acceptance before declaring the UI journey completed.

## Rollback plan

- Disable AI repair through the existing authoring kill switch; transient candidates require no
  cleanup.
- Hide/revert the Studio manifest presentation while retaining shared compiler services and any
  already valid immutable candidate releases.
- Restore the server-rendered compatibility view only if necessary; do not restore duplicated
  validation logic.
- No database rollback is expected because no migration is planned.

## Risks

- Refactoring `CompileError` could accidentally change canonical acceptance or exception handling.
- A requirements analyzer can drift into a second compiler if it does not reuse canonical logic.
- Structured messages can leak tenant-private artifact or provider details if context is not
  allowlisted.
- Preflight can become stale before compile; final transactional revalidation is mandatory.
- Moving release controls into an authoring UI can blur author versus release-manager authority.
- The concurrent authorization redesign can cause duplicated or obsolete role checks.
- React-memory state is intentionally lost on reload and can still be exposed by a platform XSS.
- AI repair may regress valid nodes, repeat the same error, increase provider cost or be influenced
  by prompt injection.
- Automatically selecting ambiguous dependencies could create a semantically wrong but valid
  release.

## Open questions

No blocking product question remains for Milestones 0–2 under the locked decisions above.

The optional platform-owned authoring-agent scenario requires a separate spike/ADR after this task
is verified. That decision must address bootstrap availability, immutable ownership, tool
attenuation, loop/turn budgets, provider failure and independence from user-editable releases.

## Status

**Implementation complete; offline verified — 2026-07-30.** Milestones 1 and 2 are implemented:
Studio manifest composition, safe canonical diagnostics, no-write preflight, dependency-role
analysis and human-triggered transient AI repair. Automated evidence is recorded in
[verification.md](verification.md). Authenticated browser/accessibility acceptance, a live approved
provider smoke and PostgreSQL-only RLS suites remain environment/owner-gated; the task is not
archived pending that acceptance. No migration or runtime-state change was made.

## Completion criteria

- All applicable acceptance criteria have separate implementation and verification evidence.
- Current docs describe Studio as the single authoring/manifest surface and preserve lifecycle
  distinctions.
- Formatter, lint, type, backend/frontend, PostgreSQL/RLS, authorization, privacy/redaction,
  accessibility and browser checks are recorded.
- Final staff-engineer, AppSec and SRE reviews find no unresolved high-severity issue.
- Checks not run, unverified assumptions and residual risks are explicitly recorded.
- Master/Phase 2.8 planning status is updated only after evidence, then the task is archived under
  planning policy after owner acceptance.
