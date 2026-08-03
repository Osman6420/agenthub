# Threat Model: scenario-studio-authoring-journey-closure-part-1

## Assets

- Prompt/artifact bodies, immutable versions, checksums, logical descriptions, and release usage.
- Scenario, project, organization, actor, draft, and exact artifact identifiers.
- Audit integrity and platform secrets excluded from artifact bodies.

## Actors

- Scenario viewer, scenario author, same-tenant unauthorized user, cross-tenant user, and workerless
  console runtime.

## Entry points

- Artifact draft list/create/detail/update/delete/diagnostics/publish.
- Exact scenario artifact preview and manifest picker actions.
- Workflow/prompt publish controls.

## Trust boundaries

- Browser/session/CSRF boundary to operator API.
- Scenario authorization boundary to tenant artifact storage.
- Mutable draft to canonical immutable artifact service.
- Authored prompt text to UI, validator, audit, and diagnostics.

## Data classifications

- Prompt/artifact content is tenant-confidential and may contain sensitive business data.
- IDs/checksums/descriptions are internal tenant metadata.
- Provider credentials/endpoints are restricted secrets and prohibited here.

## Authentication

- Existing authenticated operator session and CSRF protections; no bearer/CORS path.

## Authorization

- Exact scenario view for preview/read; exact scenario author for every mutation/publish.
- Server re-resolves organization/project/scenario/source artifact; client IDs carry no authority.

## Tenant isolation

- Source/preview artifact must match the authoritative scenario organization.
- Cross-tenant IDs return non-disclosing not-found responses.

## External systems

- None. Prompt editing/publishing performs no model call or network egress.

## Abuse cases

- Guess an artifact/draft ID to read another scenario or tenant's prompt.
- Copy a foreign source artifact into a local draft.
- Publish without author permission/CSRF or replay a stale revision.
- Store inline credentials, oversized JSON, script markup, or prompt text in audit/logs.
- Race publications to create duplicate versions or overwrite immutable history.

## Failure cases

- Artifact publication succeeds but draft metadata/picker refresh fails.
- Preview body is too large.
- Audit persistence fails during state mutation.
- Source version disappears or access changes before draft creation.

## Logging and audit risks

- Never log/audit prompt body, diff, secret-like values, cookies, or request payloads.
- Use safe codes and exact identifiers/checksums only.

## Mitigations

- Central scenario/object authorization, tenant-filtered queries, CSRF, and non-disclosure tests.
- Canonical body bounds, JSON object requirement, inline-secret validator, checksum, and immutable
  artifact service.
- Optimistic draft revisions and transactional publication/draft metadata update.
- Bounded preview response and React-escaped text rendering.
- Fail-closed audit transaction for mutations.

## Residual risks

- Authorized authors may intentionally place sensitive tenant data in a prompt.
- A successful publish followed by client network failure can require refresh/reconciliation; exact
  immutable history prevents corruption but not temporary UX ambiguity.

## Required security tests

- Authentication, CSRF, viewer mutation denial, same-tenant exact-scenario denial, cross-tenant
  preview/source/draft denial.
- Inline-secret, size/shape, unexpected-field, stale revision, concurrent new-version, immutable old
  version, audit rollback/redaction, and safe UI rendering tests.
