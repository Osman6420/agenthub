# Task Plan: phase-2-9-part-3-exact-role-release-runtime-controls

## Task summary

Complete Phase 2.9 Part 3 by making the existing governed release and runtime lifecycle operations
reachable from exact-scope contextual console pages, without broadening their server-side authority.

## Scope

- Restore an authorized release inventory and make release detail the lifecycle command center.
- Expose eval, promote, rollback, start/stop canary with state-specific blockers and feedback.
- Expose exact-scenario pause/resume on scenario detail for scenario runtime operators.
- Preserve exact-run cooperative cancel on run detail and prove neighboring/cross-scope denial.
- Keep organization/platform emergency controls visually and authoritatively distinct.
- Add service/view/browser evidence, current-behavior docs, and archived verification.

## Non-goals

- No lifecycle policy rewrite, new capability, implicit transition, hard process termination, or
  public API change.
- No production access/data, dependency, secret, egress, authentication, or tenant-isolation change.
- No Part 4 artifact/profile authoring surface.

## Trust boundaries and authorization

Browser visibility is non-authoritative. Every POST re-resolves the exact release/scenario/run and
uses existing `scenario.release`, `runtime.pause`, `runtime.resume`, or `runtime.cancel` decisions.
Same-tenant other-scenario and foreign identifiers remain non-disclosing. Platform/organization
emergency controls do not imply scenario authority and scenario operators do not gain broader scope.

## Data and operational impact

No schema migration. Existing release, canary, runtime-control, run-cancellation, and audit records
are mutated through their current transactional services. Pause is cooperative admission/safe-point
control, cancel is cooperative per-run cancellation, and neither kills processes.

## Implementation steps

1. Inspect exact current routes, services, templates, tests, runtime state, and audit findings.
2. Add contextual release inventory/detail actions and redirect every result to the exact release.
3. Add exact-scenario runtime control state/action to scenario detail; retain distinct admin surface.
4. Add matched allow/deny/direct-route/state/idempotency tests and current-build browser evidence.
5. Update docs/plans, run applicable SQLite/PostgreSQL/frontend/static gates, review, archive, commit,
   and continue to Part 4.

## Rollback

Revert the UI/routes while retaining domain services. Operational rollback uses release rollback,
canary stop, scenario resume, or the existing cooperative run cancellation semantics.

## Risks

Misleading state/action visibility, forged POSTs, stale release state, cross-scope discovery,
confusing emergency versus exact-scenario controls, and unconfirmed high-impact actions. Mitigate
with trusted re-resolution, exact capability checks, POST/CSRF, state-specific controls, explicit
copy/confirmation, contextual redirects, redacted audit, and matched denial tests.

## Status

Implemented and verified 2026-08-01. See `verification.md` and the completion-date archive.
