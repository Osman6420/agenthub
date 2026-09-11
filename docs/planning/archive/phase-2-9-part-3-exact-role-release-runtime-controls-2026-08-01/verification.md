# Verification: phase-2-9-part-3-exact-role-release-runtime-controls

## Result

Implemented and verified 2026-08-01. Existing release and runtime domain services now have reachable,
exact-role contextual console surfaces; no capability or lifecycle policy was broadened.

## Automated evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Target SQLite | Passed | 29/29 Part 3, release action, Part 1, and runtime-control tests |
| Target PostgreSQL | Passed | Same 29/29 with real PostgreSQL tenant/RLS profile |
| Broad blast radius | Passed | Console + releases + agents: 290 passed, 2 PostgreSQL-only skips |
| System/migrations | Passed | `manage.py check` clean; `makemigrations --check --dry-run` no changes |
| Ruff/diff | Passed | Changed Python files formatted/linted; `git diff --check` clean |
| Frontend | Passed | 8 files/29 tests and TypeScript/Vite production build; existing React `act` warning only |
| Target mypy | Baseline-limited | No error in changed view; four unchanged imported baseline errors in assignment/tenancy/forms remain |

The first broad run produced one expected obsolete assertion requiring `/console/releases/` to
redirect to Projects. Part 3 deliberately restores this route as a first-class exact inventory; the
old parameter was removed and the new inventory/exact-hiding behavior is covered directly. The full
broad matrix then passed.

## Authorization and security evidence

- Release inventory shows only scoped releases; exact same-tenant other-scenario releases are absent
  and direct detail is 404.
- Release lifecycle POSTs remain `_manageable_release` guarded and POST-only; neighboring editor
  promotion is 403 and state remains candidate.
- Scenario pause/resume resolves through the actor's scoped scenario queryset before central exact
  capability authorization. Same-tenant other-scenario is 404; exact editor is 403.
- Canary stop resolves only through the actor's scoped releases before exact manage authorization.
- Disabled organizations render release and active-canary controls read-only; direct service-side
  lifecycle denials remain authoritative.
- Run cancel retains exact `runtime.cancel` reauthorization and cooperative transition semantics.
- Confirmation is progressive enhancement only; server authorization remains authoritative.

## Browser and UX evidence

On the current local build, a temporary exact release-manager/runtime-operator identity:

- opened `/console/releases/` as an exact inventory instead of a dead redirect;
- opened candidate release #8 and saw eval/canary/promote actions plus the missing-suite blocker;
- submitted eval and received stable `EVAL_SUITE_NOT_PINNED` feedback on the same release page;
- reached the bounded consumer/TTL canary form;
- paused and resumed only the exact scenario through an explicit confirmation dialog, with truthful
  state and success feedback;
- saw only exact-scenario workflow runs and the existing per-run cancel surface contract.

Release/runtime layouts were visually checked at 390, 900, and 1440 px. The QA identity was
deactivated after use; the scenario was left resumed and no release promotion/canary was performed.

## Architecture, data, operations, and residual risk

No schema, public API, dependency, secret, egress, or authentication change. Release detail is the
lifecycle command center; scenario detail owns exact runtime controls; organization/platform
emergency controls remain on Runs and dominate narrower controls. State changes continue through
existing transactional, audited services.

Cooperative pause/cancel can complete only at safe runtime boundaries. The repository-wide mypy
baseline remains nonzero in four unchanged imported locations and is owned by Part 7. No production
system/data was accessed.

## Final status

Verified and completed 2026-08-01. Part 4 is next.
