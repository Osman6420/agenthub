# Verification: Scenario Studio manifest composition and AI repair loop

Date: 2026-07-30

## Verified implementation

- Scenario Studio owns exact candidate-manifest composition; the scenario overview links to Studio
  and no longer renders an editable duplicate.
- Manifest request IDs and roles are closed, bounded and tenant re-resolved. Canonical preflight
  always rolls back compiler-created rows.
- Compiler failures have stable safe codes and allowlisted context. Failed preflight/compile keeps
  the React selection; successful compile creates only an existing candidate release.
- Exact published workflow analysis reuses the canonical workflow compiler and identifies root,
  transform, tool, generate, child-workflow and agent-loop dependency roles.
- AI repair is one human-triggered transient turn. Context and diagnostics are recomputed on the
  server, provider input sections are separated, output is revalidated and no row is created until
  explicit draft save.
- Release operations use the central exact-scenario capability decision. Author-only, unauthenticated,
  CSRF and foreign-tenant paths fail closed.
- Compile success/failure and AI repair outcomes use bounded redacted audit fields; candidate bodies
  and user instructions are not recorded.

## Automated evidence

| Check | Result |
| --- | --- |
| Focused backend integration: releases authoring/compiler, builder API, scenario console, Phase 2.8 Part 4 | Pass: 93 |
| Full backend `pytest -q` | 1034 passed, 60 PostgreSQL/environment skips; four setup errors were caused by an inaccessible host pytest temp directory |
| Temp-dependent rerun with unique workspace `--basetemp` | Pass: 6, including all four previously blocked tests |
| Changed Python Ruff format/lint | Pass |
| Changed Python mypy | Pass: 6 modules |
| `manage.py check` | Pass |
| `manage.py makemigrations --check --dry-run` | Pass: no changes |
| Full frontend Vitest | Pass: 8 files, 29 tests |
| Frontend TypeScript typecheck | Pass |
| Frontend production build | Pass: Vite bundle generated |
| `git diff --check` | Pass |

## Security, authorization and data evidence

- Tests cover exact release authority, author denial, cross-tenant artifact non-disclosure, malformed
  and duplicate manifest rows, CSRF, no-write preflight, safe compile failure, success audit and
  audit-failure rollback.
- AI repair tests prove exact scenario/project scoping, author denial, server recomputation of
  diagnostics/context, no draft/artifact/release persistence and audit redaction of candidate/user
  instruction content.
- No dependency, migration, public gateway contract, authentication policy or runtime lifecycle
  transition changed.

## Review conclusions

- Staff-engineer review: canonical compilers remain the final authority; the requirements analyzer
  is advisory and the final compile repeats all checks.
- AppSec review: browser IDs, roles, context metadata, diagnostics and model output remain untrusted;
  tenant resolution, authorization, size/depth/rate limits and safe serialization fail closed.
- SRE review: preflight is rollback-only, compile and required audit are atomic, provider failures
  create no durable state, and the existing AI kill switch/profile pin remains effective.

## Not yet verified

- Authenticated browser journey, responsive layout, keyboard/focus/screen-reader behavior and visual
  acceptance.
- Live approved-provider repair smoke.
- PostgreSQL-only FORCE RLS/row-lock suites skipped by the local SQLite test configuration.

These are manual/environment acceptance items; they do not invalidate the offline implementation
evidence above.
