# Verification: prompt-logical-id-dot-compatibility

## Evidence

- Reproduced in the live `external-demo` scenario with exact artifact
  `wikipedia-brief.prompt:v1`; the original response was `logical_id_invalid`.
- Live inventory: all 43 distinct local artifact logical IDs match
  `^[a-z0-9][a-z0-9._-]{0,127}$`.
- Focused backend regression: 5 passed. Dot-bearing source copy succeeds; uppercase, traversal,
  slash, and leading-dot IDs remain rejected.
- Source-version retry test proves the same draft is returned with HTTP 200 and no duplicate row.
- Builder page tests: 3 passed. Ruff format/check and mypy passed for changed Python files.
- Frontend App/manifest tests: 8 passed; TypeScript and production Vite build passed.
- Live web health returned 200 after controlled restart.
- Browser rerun loaded `builder.js?v=prompt-artifact-authoring-2`, opened
  `wikipedia-brief.prompt:v1`, selected **Yeni sürüm olarak düzenle**, and displayed the prompt editor
  with the exact logical ID and original text.

## Review

- Architecture: validation now matches established immutable registry identity syntax; retry reuses
  mutable author state without overwriting it.
- Security: the closed lowercase allowlist still rejects path separators/traversal and remains
  bounded to 128 characters. Authorization, CSRF, tenant scope, audit metadata, and immutable source
  behavior are unchanged.
- Operations: no migration, dependency, worker, or public API change. Asset cache versioning prevents
  stale Studio JavaScript after deployment.

## Status

Implemented and verified on 2026-08-03; ready for isolated commit.
