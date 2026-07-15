# Task Plan: phase-2-5-part-6-scenario-studio

## Task summary
Unify scenario authoring, canonical workflow diagnostics, reusable immutable artifact selection and
release lineage in one Turkish-first Scenario Studio without introducing a second DSL or bypassing
the existing publish, compile, evaluation or promotion gates.

## Background
Phase 2.5 Part 6 maps to P2.5.5 and the authoring sections of P2.5.2. The repository already has a
tenant-scoped mutable `WorkflowDraft`, a graph/JSON builder, canonical workflow validation,
immutable `ArtifactVersion` publication, exact release-manifest pins and scenario/release detail
pages. These capabilities are split across the generic builder, artifact inventory and scenario
detail. Non-workflow `ArtifactDraft` currently supports only input/output contracts and deliberately
has no publish route. Part 6 must compose these authorities rather than create a parallel schema or
silently broaden the artifact types that can be authored.

## Scope
- Make the scenario detail page the entry point for a scenario-scoped studio showing authored,
  published and active state as distinct lifecycle stages.
- Deep-link the existing builder to an authorized scenario/project context and preserve its
  canonical graph/JSON round-trip and backend diagnostics.
- Display pointer-bound, stable diagnostics in JSON and graph views without reflecting secrets or
  raw server exceptions.
- Add an organization-scoped reusable artifact selector for artifact roles accepted by the release
  compiler; show type, logical identity, exact version, checksum and immutable status.
- Persist only explicit draft/reference choices or exact release-manifest pins. Selection must not
  update or clone the chosen immutable artifact.
- Protect mutable Studio authoring state with optimistic concurrency: every update carries the
  revision the author read, stale writes fail with a stable conflict response, and the UI preserves
  the unsaved candidate so one editor cannot silently overwrite another editor's newer work.
- Show workflow/agent definitions, input/output contracts, prompt/model/retrieval/tool bindings,
  document-set and consumer relationships, candidate/active release artifacts and release history.
- Reconcile the architecture/authoring guide with the exact implemented Studio contract and add a
  copyable, versioned LLM authoring section whose output still passes canonical validation.
- Add authorization, cross-tenant, type-compatibility, compiler round-trip, redaction, audit and
  release-boundary tests.

## Non-goals
- The governed transform/retrieval DSL planned for Part 7.
- OpenAI-compatible gateway adapters planned for Part 8.
- Automatic publication, release compilation, evaluation, promotion or rollback.
- Broadening canonical validators for artifact types that are currently inventory-only.
- Cross-organization artifact reuse, mutable shared artifacts or artifact deletion.
- A new graph schema, compiler, runtime, authentication mode, public API or production dependency.

## Acceptance criteria
- An authorized scenario author can enter the Studio from a scenario and edit a scenario/project-
  scoped workflow draft in graph or canonical JSON form.
- Graph → JSON → graph round-trips preserve the same canonical workflow body and compiler checksum;
  invalid input produces stable diagnostics associated with the relevant JSON pointer/node/edge
  where the existing compiler can identify one.
- The Studio distinguishes mutable draft, latest immutable publication, candidate release and active
  release; no edit or selection changes served runtime behavior.
- Reusable artifact choices contain only published immutable versions from the active organization
  and only types compatible with the selected manifest role. Cross-tenant and incompatible IDs are
  rejected server-side even if forged.
- The selected exact type/logical ID/version/checksum is visible before release compilation and the
  release compiler remains the final authority that resolves and revalidates every pin.
- Existing releases retain their exact artifacts when a newer artifact version is published.
- Concurrent authors cannot silently overwrite newer draft or manifest-authoring state; stale
  updates are rejected without losing the submitting author's candidate in the browser.
- Auditors can inspect safe Studio state but cannot create/update/delete/publish drafts or change
  release inputs. Unauthenticated, unauthorized and cross-tenant requests fail closed.
- Raw prompts, draft bodies, document content, credentials, tool endpoints and server exceptions do
  not enter logs/audit metadata or unintended list/detail projections.

## Affected components
- `apps.console`: scenario Studio route/context, templates, forms and focused tests.
- `apps.builder`: scenario-context validation, diagnostics projection and draft/reference services
  only where existing models/contracts can safely support them.
- `apps.artifacts`: read-only compatible-version projections; canonical validation and immutable
  publication remain authoritative.
- `apps.releases`: manifest-role compatibility and exact-pin compilation remain authoritative.
- `docs/architecture`, `docs/manual-testing-guide.md`, Phase 2.5 planning and task evidence.

## Interfaces affected
Additive authenticated console HTML/JSON endpoints may be introduced. Existing builder, artifact,
release, GitOps, gateway and MCP contracts remain backward compatible. Any discovered need to alter
authorization or a public API stops implementation for explicit owner approval.

## Data impact
Prefer existing `WorkflowDraft`, `ArtifactDraft`, `ArtifactVersion` and `ScenarioRelease` records.
Before adding persistence, prove that an explicit scenario-to-authoring-draft/reference link cannot
be represented safely by existing project/scenario/release data. Any additive model must carry
direct organization/scenario lineage, database constraints and PostgreSQL FORCE RLS; it requires a
separate migration/rollback review before implementation.

## Security impact
The Studio combines mutable untrusted JSON, immutable shared artifacts, compiler diagnostics and
release inputs. Canonical backend validators, bounded bodies, inline-secret rejection, explicit
safe projections and exact-pin revalidation remain mandatory. Client-side graph state is never an
authority.

## Authorization impact
Reads use existing organization membership scope. Draft authoring/publish uses
`can_author_scenarios`; release compilation/evaluation/promotion continues to use its existing
release-manager authorization. Artifact reuse grants no permission to mutate the artifact and never
crosses organization boundaries.

## Observability impact
Reuse existing structured builder/release audit events. Add events only for durable Studio state
changes, recording safe actor/organization/scenario/draft/artifact references, action, decision,
outcome and request ID. Never record artifact/draft bodies, prompt text or credentials. Preserve the
current fail-closed transaction behavior where an audited mutation requires its audit write.

## Migration impact
None expected during the first implementation pass. If direct scenario draft/reference persistence
is necessary, use an additive nullable-compatible migration, RLS policy migration, forward/backward
tests and a rollback that leaves immutable artifacts/releases intact.

## Dependencies
Verified workflow builder/compiler, immutable artifact registry, release compiler/lifecycle,
scenario relationship console and Parts 1–5 navigation/lineage work.

## Implementation steps
1. Inventory builder, artifact and release public/shared symbols and all callers before changing a
   shared service; document the exact role→artifact-type compatibility already enforced by the
   release compiler.
2. Define one server-owned Scenario Studio view model that separates draft, published, candidate and
   active state and exposes only safe bounded metadata.
3. Add scenario-scoped builder entry/deep-link validation, optimistic revision checks for mutable
   Studio state and canonical JSON/graph round-trip; enrich diagnostics with stable
   pointer/node/edge locations only from trusted compiler output.
4. Implement a tenant-scoped compatible artifact query and forged-selection validation. Route any
   durable selection through draft/reference state or the existing exact release compiler manifest;
   do not mutate `ArtifactVersion`.
5. Compose the Studio UI: authoring definition, reusable artifacts, bindings, releases, active pins
   and copyable authoring contract, with auditor read-only behavior.
6. Add focused tests for canonical round-trip, immutable reuse, newer-version stability, role/type
   mismatch, forged IDs, cross-tenant isolation, permissions, bounds, redaction and audit failure.
7. Run focused and full SQLite plus PostgreSQL/pgvector/RLS suites without pytest `-q` or a pytest
   timeout; run Ruff, mypy, Django check, migration drift, compileall and diff checks.
8. Perform staff-engineer, AppSec and SRE final-diff review; update architecture/manual docs,
   verification evidence and Phase 2.5 status. Keep Turkish authenticated owner browser review as a
   separate explicit acceptance gate.

## Test plan
- Happy path: scenario → Studio → draft graph/JSON edit → diagnostics → immutable publish → exact
  compatible artifact selection → candidate release view, without promotion.
- Round-trip fixtures prove canonical body/checksum equality and stable ordering.
- Invalid node/edge/schema, oversized/deep JSON, inline-secret-like values and malformed artifact
  references fail with bounded safe diagnostics.
- Authentication failure, auditor mutation denial, insufficient role denial, forged scenario/draft/
  artifact IDs and cross-tenant reads/writes fail without existence leakage or mutation.
- Role/type compatibility, same-org filtering, exact version/checksum revalidation, stale/missing pin
  and publication of a newer version are covered.
- Audit success/failure, body/prompt/credential redaction and CSRF are covered for every new durable
  mutation. Two-editor tests prove an update with the current revision succeeds, an update with a
  stale revision returns a stable conflict without mutation, and retry after explicit refresh or
  reconciliation cannot bypass authorization or canonical validation.
- Existing builder API, GitOps artifact import/export, release compiler/lifecycle and scenario detail
  tests remain green.

## Rollout plan
Additive console rollout behind existing authenticated navigation. Apply any additive migration
before exposing its route, then restart local web/worker following manual-testing section 0 and run
an authenticated Turkish scenario journey. No automatic runtime activation occurs.

## Rollback plan
Remove the additive Studio routes/templates/projections and any new draft/reference writes. Existing
immutable artifacts and releases remain authoritative and are not deleted. Reverse an additive
migration only after proving no retained authoring data is required.

## Risks
- A generic selector can create type-confused manifests unless role compatibility is enforced on the
  server and again by the release compiler.
- Scenario/project association is currently looser than direct draft ownership; an unsafe deep link
  could expose or edit another project's draft.
- Rich diagnostics can echo author content or internal exceptions.
- UI wording can imply that publish or artifact selection changes the active runtime.
- Adding revision checks only to workflow JSON while leaving reusable-artifact/manifest authoring
  state unprotected would preserve a partial lost-update path; every mutable Studio aggregate must
  use the same conflict contract.

## Open questions and implementation gates
- Confirm whether Studio needs a durable direct scenario→draft/reference association. If yes, update
  this plan and threat model before creating a migration. Any mutable model introduced for that
  association or artifact selection must include an atomic revision field; do not implement
  last-write-wins updates.
- Confirm the exact release manifest role→artifact-type matrix from compiler code; do not infer it
  from UI labels.
- Authentication/authorization/public API/dependency changes are not authorized by this plan and
  require explicit owner approval if discovered.
- Authenticated Turkish owner browser acceptance remains a manual completion gate.

## Status
Implemented and automated-verified. Workflow drafts carry direct nullable scenario lineage and
revision-based optimistic concurrency; the scenario page deep-links that scoped draft into the
canonical builder and composes published immutable artifacts into an exact candidate release
manifest. Role/type compatibility, tenant scoping, release-manager authorization and fail-closed
audit behavior are enforced server-side. Authenticated Turkish owner browser review remains.

## Completion criteria
Implementation and negative security tests pass on SQLite and PostgreSQL/RLS; static, schema,
migration and final-diff checks pass; architecture/manual/verification records match the delivered
contract; authenticated Turkish owner review is reported separately.
