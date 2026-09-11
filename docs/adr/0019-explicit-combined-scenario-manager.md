# ADR 0019: Explicit combined scenario management

- **Status:** Accepted
- **Date:** 2026-09-09

## Context and decision

The owner selected combined editing, publishing and operations for project/scenario
managers in the [unified task](../tasks/Agent_Hub_MD/plan.md). ADR-0015's typed,
exact-scope assignment model remains the authorization foundation.

Add explicit `project_editor`, `project_manager` and `scenario_manager` responsibilities.
Scenario management combines view/edit/test/release, access management and runtime
view/cancel/pause/resume. Project managers administer their project's basic roles and
scenario access; editors may create scenarios. They cannot delegate specialist,
organization, platform or document responsibilities.

Scenarios use a closed `legacy` / `inherit` / `private` access mode. Inheritance maps
the three basic project roles to their scenario counterparts and ignores direct basic
scenario roles. Specialists remain independent. Private scenarios use explicit direct
roles; project managers can administer access and explicitly add themselves, but gain
no implicit content visibility. An authorized single-scenario user sees only the parent
project navigation shell and authorized siblings.

New console scenarios explicitly select inherited or private access; the initial form
selection is inheritance. Inheritance requires a permanent project manager; private
creation requires an explicitly selected active member as permanent scenario manager.
Existing data and low-level/GitOps creation retain the legacy default.

Keeping only separate specialists would contradict the selected management
experience. Broadening existing editor or release-manager rows would silently
expand authority. A new explicit role avoids both problems.

## Security and operational consequences

Document content, retrieve grants, tool approval, organization administration and
platform authority remain separate. An assignment never authorizes a sibling
scenario. Active membership, active user, expiry, revocation, inactive-organization
policy and release readiness checks still apply. Run navigation and list scope
include this new runtime-capable role; mutation endpoints reauthorize the target.

Project and scenario transition screens show effective gains/losses before applying.
Signed previews are actor/target/baseline bound, expire after ten minutes, and recheck
authorization under organization locks. A stale preview cannot overwrite intervening
changes. Application and its audit receipt commit atomically; replay is idempotent.
Bounds are 500 members, 5,000 role rows per scope, and 200 scenarios / 5,000 changed
member-scope rows for a project preview. Legacy project administration and independent
specialists are preserved. Routine removal of the last permanent manager is rejected;
security offboarding remains available to organization administrators, who can restore
management to another eligible member.

Grant and revoke use existing transaction/audit boundaries. No provider, secret,
dependency or authentication mechanism changes. Metadata/status checks do not
replace release evaluation, callability or broader runtime suspension controls.

Candidate preparation is an edit-or-release action, consistently evaluated through
`identity.scenario_actions`. Django and React receive the same `allowed_actions`;
organization-wide write flags cannot replace an exact scenario decision. Compilation
reauthorizes under organization/scenario locks and commits with its audit receipt.
Publication, rollback, canary and callability still require release authority.
Readiness is a separate gate; permission does not mean a candidate is ready to serve.

Consumer access uses closed options in the normal console. Running a scenario adds
only `workflow_run`; tools and diagnostic/ingestion reads require explicit choices.
Side-effect tools additionally require tool-call access and keep human-approval gates.
Legacy technical values remain supported by existing records/API/GitOps; normal forms
do not expose inactive capabilities or accept a forged raw capability list.

## Migration and rollback

Identity migrations 0013/0014 add choices; catalog 0009/0010 add scenario access
mode and project/scenario concurrency receipts. They rewrite no role assignment and
preserve existing IDs and references. New assignments and mode changes are explicit.
Do not roll back to a binary that ignores access modes after private/inherited modes
are in use: it could restore legacy implicit visibility or omit new management roles.
Keep the mode-aware authorization layer during application rollback. Schema reversal
and historical role restoration are not an operational permission rollback.

## Verification and references

- [Task evidence](../tasks/Agent_Hub_MD/plan.md#11-doğrulama-kaydı-ve-devam-noktası)
- [ADR-0015](0015-responsibility-based-operator-authorization.md)
- [Central evaluator](../../apps/identity/authorization.py)
- [Role and denial tests](../../apps/identity/tests/test_scenario_manager.py)
- [Real console release tests](../../apps/console/tests/test_scenario_manager_actions.py)
