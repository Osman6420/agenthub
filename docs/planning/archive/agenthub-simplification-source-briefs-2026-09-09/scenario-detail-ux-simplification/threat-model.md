# Threat Model: scenario-detail-ux-simplification

## Assets

- The active scenario/release pointer and consumer traffic.
- Immutable release manifests, artifact checksums and evaluation evidence.
- Scenario drafts and unpublished changes.
- Tenant-scoped document bindings, indexes and consumer grants.
- Runtime/lifecycle control state and audit history.

## Actors

- Scenario Viewer and Editor.
- Scenario Release Manager.
- Scenario Runtime Operator.
- Document-set Manager/Content Reader.
- Organization/platform administrator.
- Same-tenant user without authority over the exact scenario.
- Cross-tenant authenticated user.

## Entry points

- Scenario detail GET and its authoring, test, lifecycle and runtime POST routes.
- Release detail, promotion, rollback and canary routes.
- Scenario Studio/operator builder API.
- Document-set and consumer relationship routes linked from scenario detail.

## Trust boundaries

- Browser presentation to server authorization: visible/hidden buttons are never authority.
- Mutable Studio draft to immutable published artifact/release.
- Evaluation result to release promotion gate.
- Scenario access to separately governed document content and document-set operations.
- Scenario alias/binding to public consumer execution.

## Data classifications

- Scenario names, release IDs, roles and checksums: tenant-internal metadata.
- Draft prompts/workflow bodies and evaluation questions/answers: tenant-confidential.
- Document text: protected content with a separate content-read grant.
- Tokens, provider secrets, endpoints and authorization headers: secrets; never render or log.

## Authentication

Unchanged session/LDAP authentication for console routes and existing CSRF protection for state
changes. No anonymous or consumer-bearer route is added.

## Authorization

No authority may be widened by the new primary-action selector or page read model. Every linked or
submitted action must reach the existing exact-scenario/domain authorization check. Authoring,
release, runtime, document and consumer-access responsibilities remain separate and deny by default.

## Tenant isolation

All scenario, release, draft, evaluation, document and consumer queries must remain constrained to
the resolved organization and exact authorized object. Foreign IDs must return the existing safe
denial behavior without existence disclosure.

## External systems

None added. The page must not initiate model, embedding, document or connector egress merely to
calculate or render readiness.

## Abuse cases

- An Editor triggers promotion through a simplified combined CTA.
- A user forges a release/scenario/document ID behind a visible link.
- A summary leaks another tenant's release, client, draft or document metadata.
- A viewer infers protected document content from test evidence or source snippets.
- A GET navigation causes a state change.
- Simplification hides an active suspension or failed evaluation and encourages unsafe promotion.

## Failure cases

- Active release exists but no mutable Studio draft exists.
- A draft exists but is newer than the last published workflow.
- Candidate evaluation is queued, failed, stale or absent.
- Required retrieval binding/index is absent or not ready.
- Organization/scenario is disabled or runtime is suspended at a broader scope.
- The newest database release is not the release the user expects to promote.

## Logging and audit risks

Do not move domain transitions into template/view convenience code that omits existing audit events.
New page-render telemetry, if added, must be bounded and contain no prompt, answer, document text,
token, secret, endpoint or raw manifest.

## Mitigations

- Derive display state from authoritative services/models; keep enforcement in existing domain
  services.
- Keep state changes POST-only, CSRF-protected, exact-object reauthorized and audited.
- Show critical blockers/suspensions even when detailed controls are collapsed.
- Link technical metadata to release detail instead of copying artifact bodies into scenario detail.
- Render protected evidence only after the existing content-read authorization check.
- Test role and tenant matrices against both rendered affordances and direct route calls.

## Residual risks

- Product terminology may still be misunderstood without user testing.
- Existing legacy records can expose combinations not represented in initial fixtures.
- Presentation tests cannot prove runtime/compiler invariants; existing domain suites remain required.

## Required security tests

- Viewer/editor cannot promote, activate, roll back, canary or change runtime state without exact
  authority, including direct POST attempts.
- Release Manager does not gain document content read or Studio edit implicitly.
- Runtime Operator does not gain release or authoring authority.
- Same-tenant neighboring-scenario and cross-tenant identifiers fail safely.
- GET requests to every new destination are read-only; mutation routes retain CSRF and POST-only
  enforcement.
- New summaries contain no prompts, answers, document content, secrets, endpoints or raw manifests.
- Critical suspension, failed evaluation and missing-index blockers cannot be hidden by a false
  ready/primary-action state.
