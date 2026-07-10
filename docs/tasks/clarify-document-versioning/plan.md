# Task Plan: clarify-document-versioning

## Task summary

Clarify that `v3` identifies the third revision of the target-architecture document, not an AgentHub product generation or a dependency on a v2 application.

## Background

The target document currently describes itself as converting a v2 RAGaaS architecture, includes a v2-to-v3 migration section, and reuses `v3` as the GitOps schema version. This incorrectly suggests that a v2 application must exist.

## Scope

- Clarify the document revision and greenfield implementation baseline.
- Remove the v2 application/import/migration assumption from current planning documents.
- Separate the GitOps schema version from the document revision by using `agenthub/v1`.
- Preserve the existing filename so repository links remain stable.

## Non-goals

- Renaming archived design documents.
- Changing artifact logical versions such as `prompt:v3`.
- Changing the public HTTP API mounted at `/v1/`.
- Modifying unrelated control-plane authoring work.

## Acceptance criteria

- [x] The target plan states that no v2 application, release, configuration, or document is required.
- [x] `v3` is explicitly defined as the document revision.
- [x] The v2 migration section no longer claims an implemented/required migration path.
- [x] GitOps examples and implementation use schema version `agenthub/v1`.
- [x] Existing GitOps import behavior remains compatible with previously authored documents.
- [x] Current planning/architecture summaries do not retain the v2-predecessor assumption.

## Affected components

Target-architecture documentation, master planning, architecture overview, GitOps artifact export, and GitOps tests.

## Interfaces affected

Newly exported GitOps documents identify their schema as `agenthub/v1`. Import currently does not enforce `api_version`, so previously authored documents remain importable.

## Data impact

No database or persisted artifact-body migration.

## Security impact

None. Secret validation and tenant scoping remain unchanged.

## Authorization impact

None.

## Observability impact

None.

## Migration impact

No database migration. Existing GitOps files remain accepted by current import behavior.

## Dependencies

Existing artifact GitOps unit tests and repository Markdown checks.

## Implementation steps

1. Correct terminology in the target plan and current source-of-truth documents.
2. Change the independent GitOps schema identifier to `agenthub/v1`.
3. Update/add focused tests and verify repository references.

## Test plan

Run GitOps artifact tests, Ruff, relevant Markdown link checks, and a final diff review.

## Rollout plan

Ship as a documentation and GitOps export-label correction. Communicate that `agenthub/v1` is the first schema version.

## Rollback plan

Revert the scoped documentation, constant, and test changes together.

## Risks

External consumers may have begun relying on the accidental export label. Import compatibility is retained; human review should confirm no external schema registry treats `agenthub/v3` as authoritative.

## Open questions

None for implementation. External GitOps consumer inventory remains a manual review item.

## Status

Verified

## Completion criteria

Acceptance criteria are evidenced in `verification.md` and the applicable checks pass.
