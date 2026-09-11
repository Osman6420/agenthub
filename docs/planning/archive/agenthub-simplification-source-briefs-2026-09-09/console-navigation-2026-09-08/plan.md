# Console navigation and scenario entry point

## Scope and acceptance

Owner requested a dedicated Scenarios sidebar entry and review/correction of all page
transitions. Deliver a real scenario index using existing scoped querysets, consistent
active navigation, discoverable related screens and explicit parent/cancel links.
Review live reachable page families and all console templates/routes; distinguish
unreachable/data-dependent screens from executed browser journeys.

1. Inventory console routes/templates and visit each reachable page family read-only.
2. Restore `/console/scenarios/` as a bounded, searchable/project-filtered list with
   canonical detail links and project-bound creation (existing authorization preserved).
3. Centralize active navigation presentation, including scenario children, documents,
   tests, runs/approvals and management. Correct dead ends and misleading links.
4. Add navigation/scoping regressions; run relevant console tests and static checks.
5. Verify affected/adjacent live journeys, responsive/keyboard behavior, browser errors;
   document unverified role journeys without claiming they ran.

## Boundaries

No dependency, public API, schema, authorization-policy, tenant-isolation or lifecycle
changes. Existing local changes belong to prior tasks. Do not reset data, seed identities,
change credentials, publish scenarios or activate indexes in the existing live application.
The repository-owned disposable browser gate may seed its isolated synthetic database;
use a separate localhost cookie scope to preserve the user's live 127.0.0.1 session.
Read existing scoping/authorization as source of truth; display filters can only narrow.
No broad redesign implementation is implied by this navigation increment.

## Risks and rollback

See [threat-model.md](threat-model.md). Main risks: foreign/same-tenant record disclosure,
loss of project context, unsafe return URLs, hidden actions and stale active markers.
Use named internal URLs rather than request-supplied return destinations. Existing URLs
remain valid. Roll back only this task's diff, preserving pre-existing working changes.

## Verification and status

2026-09-09 follow-up: owner repeated the dedicated Scenarios/menu and all-page transition
request. The existing implementation and evidence are already present in the working tree.
Reconcile them against today's source/runtime; traverse current reachable GET page families,
fix concrete navigation gaps, and rerun affected checks. Do not claim earlier checks were
executed today. Preserve the outstanding full lifecycle gate explicitly.
Current inspection found missing bottom cancel links on artifact/profile/grant forms
and no project-to-filtered-scenario-list shortcut. Add named-route links only; the
project shortcut is shown only for the active organization so it cannot create a
cross-workspace filter 404. Reuse existing scoping tests and verify these links in the browser.

Implemented. Scoped list and navigation automated checks and browser journeys passed as
recorded in [verification.md](verification.md). The full section 10 lifecycle mutation gate
is not complete, so this unit is not marked Verified/Completed and remains unarchived.
Codebase Memory/Serena unavailable; use bounded direct inspection and exact search.
One main agent owns implementation, review and evidence. No delegation.

Verification found a pre-existing type-check failure in scenario artifact usage counting.
The matching dictionary-key lookup now has an explicit cast after membership succeeds;
runtime behavior is unchanged. No assertion or checker was disabled.
