# Task Plan: scenario-studio-authoring-journey-closure-part-1

## Task summary

Deliver the first reviewable increment of the Scenario Studio authoring closure: exact artifact
preview in the manifest picker, first-class prompt-template drafts, edit-as-new-version publication,
required version notes, and immediate visibility of the newly published exact version.

## Background

Published artifacts are already immutable and can be viewed on a separate console detail page, but
the Studio picker is label-only. Generic `ArtifactDraft` currently supports input/output contracts
only and deliberately has no publish route. Workflow publishing also defaults an empty version note,
while the UI silently disables the button. Part 1 closes these gaps through the canonical artifact
validator and `create_artifact_version` service without changing release-manager responsibilities.

## Scope

- Extend governed artifact draft state to `prompt_template`, including logical description and last
  published version metadata.
- Create a prompt draft from scratch or from an authorized exact prompt artifact version.
- Publish a validated prompt draft as the next immutable exact version with a required change note.
- Add an authorized, bounded exact-artifact JSON preview API used inside the manifest picker.
- From a prompt preview, open an edit-as-new-version draft without losing scenario context.
- Refresh picker data and identify/select the newly published exact version without a full page reload.
- Make workflow and prompt publish controls respond to empty change notes with focus and an accessible
  inline error instead of a silent disabled control.
- Audit prompt draft creation/publication and exact artifact preview denials/success as applicable,
  without recording body content.

## Non-goals

- Retrieval/chunking/profile structured editors; these are Part 2.
- Generate-node inline prompt binding and derived multi-Generate roles; these are Part 3.
- Mutating or deleting a published artifact version.
- Changing scenario/release authorization responsibilities or public consumer APIs.
- Exposing provider credentials, endpoints, or other platform-profile configuration.

## Acceptance criteria

1. A release manager with exact scenario access can preview an artifact version offered by that
   scenario's manifest picker; cross-tenant and unauthorized exact IDs do not disclose existence.
2. A scenario author can create a prompt draft, edit prompt text, validate it, and publish it only
   with a non-empty version description through the canonical artifact service.
3. A scenario author can start from an existing exact prompt version; publication creates version
   `N+1`, leaves `N` unchanged, and preserves the logical description.
4. A viewer cannot create/update/publish a prompt draft. All mutations remain CSRF-protected and
   server-authorized.
5. Prompt bodies and secrets are absent from audit/log metadata; inline-secret validation remains
   fail-closed.
6. Newly published prompt metadata is returned to the UI, draft revision is advanced, and artifact
   options are refreshed without a page reload.
7. Empty workflow or prompt version notes show `Bu sürümde nelerin değiştiğini yazın.`, focus the
   field, and make no publish request.
8. Existing input/output draft behavior and existing workflow publish/API contracts remain compatible.

## Affected components

- `apps/builder` models, services, operator API, URLs, migrations, and tests.
- `apps/console` exact scenario artifact options/preview integration.
- `frontend` artifact draft editor, manifest picker, API/types, toolbar, and tests.
- Authoring/current-state documentation and task verification evidence.

## Interfaces affected

- Additive operator-console JSON operations for artifact-draft create/publish and exact artifact
  preview under an exact scenario.
- Existing artifact-draft response gains additive logical-description/publish metadata.
- Existing manifest option shapes remain compatible.

## Data impact

- Additive `ArtifactDraft` fields record logical description and last publication metadata; choices
  expand to prompt templates. Published `ArtifactVersion` data is unchanged and remains immutable.
- No artifact body is copied into audit metadata or server logs.

## Security impact

- Preview responses are bounded and exact-scenario/tenant authorized.
- Prompt input uses existing body-size, inline-secret, checksum, and canonical validation controls.
- HTML rendering relies on React text escaping; no raw HTML prompt rendering is added.

## Authorization impact

- Reuse `SCENARIO_VIEW` for draft/preview reads and exact existing scenario-author authorization for
  create/update/publish. No authorization predicate or role mapping changes.
- Artifact source IDs are re-resolved inside the authoritative scenario organization before copying.

## Observability impact

- Add safe audited prompt draft publish events with actor, tenant, logical ID/version/checksum and
  request ID. Body and prompt text are excluded.
- No new metrics are required for this bounded control-plane increment.

## Migration impact

- Additive builder migration only; no backfill beyond safe defaults and no destructive operation.
- Verify migration generation is clean and existing draft rows retain behavior.

## Dependencies

- Existing `ArtifactDraft`, `create_artifact_version`, `validate_body`, scenario authorization, and
  manifest picker APIs.
- No new production dependency.

## Implementation steps

1. Add Part 1 task/threat/verification records and capture the baseline.
2. Extend ArtifactDraft and its service invariants for prompt drafts and immutable publication.
3. Add scoped API routes for create/publish and exact artifact preview/edit-as-new-version source.
4. Add backend happy-path, invalid, stale, auth, cross-tenant, CSRF, audit, redaction, and immutable
   new-version tests.
5. Add prompt editor, picker preview/new-version action, selector refresh, and publish-note feedback.
6. Add frontend API/component regression tests and run focused checks.
7. Run repository-applicable gates, browser authorization/UX gate, review the diff, update evidence,
   mark status accurately, and commit Part 1 alone.

## Test plan

- Backend builder API/services and console artifact-option integration tests.
- Frontend artifact editor, manifest picker, toolbar, flow/deep-link tests.
- Migration/check, Ruff, mypy, Django check, compileall, focused/full pytest as applicable.
- Mandatory browser allow/deny/cross-tenant/direct-request/console-network/keyboard-responsive gate.

## Rollout plan

- Additive routes/fields and UI controls; existing workflow and contract draft paths remain available.
- Rebuild frontend static assets for runtime verification; generated bundle remains gitignored.

## Rollback plan

- Revert Part 1 code/UI. Additive nullable/defaulted draft fields can remain harmless during a
  forward-fix; no published exact version is removed or rewritten.
- Disable prompt draft controls while retaining existing immutable artifacts if runtime regression
  occurs.

## Risks

- Exact body preview could disclose cross-tenant content if scoped only by artifact ID.
- Concurrent publication could allocate conflicting next versions without transactional locking.
- Prompt text could leak through errors/audit or be rendered unsafely.
- UI refresh failure could make the user select a stale version.

## Open questions

- None blocking Part 1. Prompt draft bodies use the existing canonical `{ "template": "..." }`
  runtime contract; advanced JSON remains available for compatible metadata.

## Status

Implemented and verified on 2026-08-03; ready for the isolated Part 1 commit.

## Completion criteria

- All acceptance criteria have recorded evidence in `verification.md`.
- The additive migration and compatibility checks pass.
- Mandatory browser gate is recorded or explicitly left unverified with the concrete blocker.
- Final staff/AppSec/SRE review finds no unresolved high-risk issue.
- Part 1 is committed separately before Part 2 begins.
