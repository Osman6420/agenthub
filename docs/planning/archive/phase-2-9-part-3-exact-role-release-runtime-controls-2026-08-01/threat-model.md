# Threat Model: phase-2-9-part-3-exact-role-release-runtime-controls

## Assets and actors

Immutable releases, eval gates, consumer-scoped canaries, scenario admission, unified runs, runtime
controls, and audit evidence. Actors are exact release managers, exact runtime operators,
neighboring roles, unassigned/inactive users, organization/platform administrators, consumers, and
recovery superadmin.

## Entry points and abuse cases

Release inventory/detail GETs; eval/promote/rollback/canary POSTs; scenario pause/resume POSTs; run
cancel POSTs. Attackers may forge another release/scenario/run/canary ID, replay a transition, use a
neighboring role, confuse platform emergency authority with exact scenario authority, or exploit a
visible button as if it were authorization.

## Controls

- Exact scoped querysets and central capability checks on every mutation.
- POST/CSRF, trusted parent/tenant lineage, lifecycle state gates, row locking/idempotent services.
- Non-disclosing 404 for inaccessible objects and 403 for an accessible object lacking the action.
- Separate wording and layout for scenario controls versus organization/platform emergency stops.
- Stable identifiers/reasons/request correlation only; no token, prompt, output, or document bytes.

## Failure and residual risk

Service/audit failure must preserve prior state where the existing lifecycle contract is fail-closed.
Runtime pause/cancel remains cooperative, so workers may stop only at a safe boundary. Browser
confirmation reduces accidental commands but cannot replace server authorization. Mandatory browser
and direct-POST evidence remains required before completion.
