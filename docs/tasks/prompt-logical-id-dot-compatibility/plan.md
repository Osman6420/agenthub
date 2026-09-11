# Task Plan: prompt-logical-id-dot-compatibility

## Summary

Fix edit-as-new-version for existing artifact logical IDs containing dots, such as
`wikipedia-brief.prompt`. Align mutable artifact-draft validation with the established registry ID
format without changing immutable versions or tenant authorization.

## Scope and risks

- Replace the overly narrow Django slug validator with a closed artifact logical-ID validator:
  lowercase alphanumeric first character, followed by lowercase alphanumeric, dot, underscore, or
  hyphen; maximum 128 characters.
- Apply it to new artifact drafts and source-version copies.
- Make source-version draft creation retry-safe and ensure the rebuilt Studio asset receives a cache
  version so the fixed transition is not masked by a stale browser bundle.
- Test dot acceptance and unsafe/uppercase/path-like rejection through service and API paths.
- Risk: accepting an unsafe separator or rejecting established IDs. Live inventory confirms all 43
  distinct local artifact logical IDs match the proposed closed format.

## Authorization, data, and operations

- No authorization, API shape, migration, dependency, or runtime-worker change.
- Existing exact artifact remains immutable; only draft creation validation changes.
- Audit continues to record safe logical ID metadata without body content.

## Verification

- Focused builder service/API tests, Ruff, mypy, frontend-independent live browser rerun.
- Apply through controlled web restart only if the mounted runtime needs URL/code reload.

## Status

Implemented and verified on 2026-08-03 with `wikipedia-brief.prompt`; ready for isolated commit.
