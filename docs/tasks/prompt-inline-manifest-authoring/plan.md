# Task Plan: prompt-inline-manifest-authoring

## Task summary

Simplify the candidate-manifest prompt picker into one inline authoring flow: choosing an exact
prompt version automatically loads its content, the prompt is editable in place, the manifest role
is derived by the UI, and the single primary action either reuses the unchanged exact version or
publishes and selects a new immutable version when the text changed.

## Background

Part 1 added exact artifact preview and new-version authoring, but the manifest picker still required
separate role, open, edit, and add actions. That composition did not match the author task and made
the prompt appear read-only.

## Scope

- Automatic bounded exact-version preview after version selection.
- Inline prompt text editing for authorized `prompt_template` versions.
- Automatic role derivation from a workflow requirement, otherwise from the artifact type.
- One contextual action: reuse the unchanged exact version, or publish and select a changed version.
- Replacement of an existing manifest entry with the same role.
- Focused component tests and live read-only browser acceptance.

## Non-goals

- Moving prompt authoring into the Generate node form; that remains the next Generate-binding unit.
- Generic inline editors for non-prompt artifact types.
- Mutating an existing published artifact version or changing server authorization.

## Acceptance criteria

1. Selecting an exact prompt version automatically displays an editable prompt textarea.
2. No manifest-role selector or separate open/edit/close buttons appear in the primary flow.
3. An unchanged prompt adds the selected immutable version under the derived role.
4. A changed prompt requires a change description, publishes a new immutable version, and selects it.
5. A selection with the same role is replaced instead of creating an invalid duplicate.
6. Users without version-authoring permission see the exact content but cannot edit or publish it.
7. API failures preserve the user's text and produce visible feedback.

## Affected components

- `frontend/src/ScenarioManifestPanel.tsx`
- `frontend/src/__tests__/scenario_manifest.test.tsx`
- Console builder static asset cache key

## Interfaces affected

No public or server interface changes. Existing authorized artifact-draft and immutable publish APIs
are orchestrated by the UI.

## Data impact

Changed prompt text creates a new immutable artifact version. Unchanged text creates no artifact.

## Security impact

Prompt bodies remain loaded through the bounded, scenario-authorized preview endpoint. The client
cannot grant authoring permission and does not render prompt text as HTML.

## Authorization impact

No authorization contract changes. `can_create_new_version` only controls the affordance; the server
continues to authorize draft creation, update, and publication independently.

## Observability impact

Existing artifact draft/update/publish audit behavior is retained. Prompt bodies are not logged.

## Migration impact

None.

## Dependencies

Existing exact-version preview, artifact draft, draft update, immutable publish, and manifest option
endpoints.

## Implementation steps

1. Refactor selector state to derive roles and auto-load exact content.
2. Add inline prompt text and change-description state.
3. Implement reuse-or-publish-and-replace manifest selection.
4. Remove redundant role/open/edit/close controls.
5. Update focused tests, build the frontend, bump the builder cache key, and verify live behavior.

## Test plan

- Auto-preview and editable prompt happy path.
- Unchanged exact-version selection with derived role.
- Changed prompt validation, immutable publish sequence, and role replacement.
- Read-only preview for users without version-authoring permission.
- Existing workflow requirement and manifest preflight/compile cases.

## Rollout plan

Ship as a frontend replacement using existing APIs. Existing exact version pins remain compatible.

## Rollback plan

Revert the frontend commit; newly published immutable versions remain valid history and are not
deleted.

## Risks

- Asynchronous previews can race when selection changes quickly.
- A failed multi-request publish flow can leave a valid unpublished draft for retry.
- Automatic role derivation must preserve workflow-required custom roles.

## Open questions

None for this focused unit.

## Status

Verified. Implemented and verified on 2026-08-03; pending isolated commit.

## Completion criteria

Acceptance criteria are implemented, focused frontend tests/typecheck/build pass, live preview is
verified without publishing test data, and verification evidence plus final diff review are recorded.
