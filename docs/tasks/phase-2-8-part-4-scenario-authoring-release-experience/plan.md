# Task Plan: Phase 2.8 Part 4 — Scenario authoring and release experience

## Task summary

Turn scenario creation and configuration into a project-context, preset-led journey; replace the
unbounded artifact registry form with typed exact-version selectors; keep Studio, graph and releases
inside the scenario; and make governed AI authoring usable in correctly configured environments.

## Background

Part 1 moved scenarios under projects and releases/artifacts into scenario detail, but creation still
exposes technical types/parents and the release candidate form lists every published artifact with a
free-text role. Part 3 replaces scenario types with one workflow engine. AI authoring already has a
safe candidate/acceptance path but reports disabled when the deployment has no approved profile ID.

## Scope

- Create scenarios only from an authorized project; inherit organization/project server-side.
- Offer three explained starters: Empty Workflow, Document Answer and Agent Loop. Presets create a
  validated draft, not an active release.
- Present a task-focused scenario summary and contextual tabs for Documents, Configuration/Studio,
  Releases and Test; retain exact technical provenance as secondary detail.
- Replace the full artifact list/free-text role form with `artifact type → logical artifact → exact
  version` selectors filtered by role/type compatibility and scenario organization.
- Describe every reusable artifact type and show version, checksum, status and dependency impact
  before selection. Never resolve “latest” at compile/publish time.
- Keep DSL/graph access and workflow drafts inside the scenario. Remove any separate primary DSL or
  artifact-registry navigation dependency.
- Show release history, active/candidate/canary status, exact pins, evaluation gate, promote,
  rollback and canary actions inside the scenario subject to existing role predicates.
- Default invocation help to a copyable `curl /v1/chat/completions` for sync-capable releases; show
  `/v1/responses` with background semantics where required. Never present `/invoke` as default.
- Configure approved immutable `AI_AUTHORING_MODEL_PROFILE_ID` and provider in the canonical local
  environment/deployment procedure. Preserve candidate-only generation, diagnostics and explicit
  draft transfer.
- Update the concise DSL guide sent to AI, detailed human guide, authoring context and Studio node
  descriptions for the verified Part 3 contract.

## Non-goals

- Reimplementing the unified engine, adding arbitrary artifact types, choosing endpoints/secrets in
  the tenant UI, auto-publishing AI output, silent release promotion or weakening compile/eval gates.
- A standalone global artifact/release/DSL experience as the normal workflow.
- Document profile/search implementation or question-set evaluation.

## Acceptance criteria

- No scenario create form exposes organization, project or removed scenario type.
- Each preset produces a valid scenario-bound draft with clear next steps and no active release.
- Artifact selectors show only tenant-authorized, published, compatible exact versions and reject
  forged/stale selections server-side.
- Release compilation continues through canonical validators and immutable manifest checksums.
- Scenario page explains draft versus published artifact versus candidate/active release.
- Curl examples match compiler-supported execution modes and use the scenario alias, not internal ID.
- AI authoring works when the approved profile/provider is configured, remains unavailable with an
  actionable safe configuration message otherwise, and cannot publish without explicit acceptance.
- Audit, disabled-org, role, cross-tenant, accessibility and responsive behavior remain enforced.

## Interfaces affected

Console project/scenario routes and forms, Studio/node schema, artifact/release selection endpoints,
AI-authoring configuration/preflight and documentation. Public gateway shapes are owned by Part 3;
this part consumes them and changes only console guidance.

## Data, security and authorization impact

Preset creation may add scenario-bound WorkflowDraft records through existing audited services; no
new moving references. Artifact option endpoints return bounded public metadata only after tenant and
role authorization. AI descriptions/model candidates are tenant-confidential and excluded from logs;
generation/acceptance retains current rate limits, pinned contracts and fail-closed audit behavior.

## Dependencies

Part 1 shell, Part 2 contextual organization/project behavior, and verified Part 3 DSL/execution-mode
contract. Existing artifact, release, eval and Studio services remain authoritative.

## Implementation steps

1. Define preset bodies against the verified DSL and test them through the canonical compiler.
2. Replace global scenario creation with project-context route and transactional scenario/draft
   creation; preserve server-generated IDs/alias and audit rollback.
3. Build bounded dependent artifact selectors backed by server-filtered endpoints/forms and canonical
   role/type validation; include descriptions and exact provenance.
4. Reorganize scenario detail/Studio/release surfaces without duplicating mutation routes.
5. Generate invocation examples from compiled supported modes and active alias/release state.
6. Enable AI authoring operationally with approved profile/provider preflight; update AI and human
   DSL guides atomically and test guide size/contract integrity.
7. Run authorization, compile/release, AI redaction, accessibility and browser regression reviews.

## Test plan

Preset compile tests; contextual create tampering/cross-tenant denial; artifact dependent-selector
filter and forged ID tests; exact version/checksum manifest tests; release lifecycle regression;
sync/background curl contract tests; AI enabled/disabled/profile mismatch/rate/audit/candidate tests;
disabled organization and role matrix; frontend/backend/accessibility/browser checks; full quality and
PostgreSQL RLS suites.

## Rollout and rollback

Roll UI changes after Part 3 is verified. Retain canonical mutation services/routes while old
presentation links redirect contextually. AI authoring can be stopped immediately by unsetting the
profile ID without deleting drafts/artifacts. Rollback restores prior presentation but keeps any
valid immutable artifacts/releases and additive drafts.

## Risks

Preset drift from DSL, forged artifact version selection, hiding provenance, confusing draft/release
state, incorrect endpoint advice, AI profile misconfiguration, model candidate leakage or accidental
publish bypass.

## Open questions

None. The preset model, contextual creation and configured-profile AI-authoring behavior are locked.

## Status

**Planned.** Not implementable until Part 3 contracts are verified.

## Completion criteria

All acceptance/tests pass; AI and human guides match the compiler; current docs and manual journeys
are updated; final staff/AppSec/SRE and UX reviews close; verification evidence reaches Verified.
