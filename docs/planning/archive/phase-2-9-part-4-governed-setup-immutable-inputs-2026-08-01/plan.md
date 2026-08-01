# Task Plan: phase-2-9-part-4-governed-setup-immutable-inputs

## Task summary

Complete Phase 2.9 Part 4 by making release prerequisites and governed platform profile setup
reachable through the console without shell/database bootstrap or any authorization/egress bypass.

## Scope

- Add guided immutable input-contract, output-contract, and eval-suite authoring/versioning from an
  exact scenario/release context through `create_artifact_version` and canonical validators.
- Add a platform-admin-only setup workspace for model, embedding, Confluence, and REST profile
  registration, disable, and the existing explicit tenant/document-set grant operations.
- Display only operational readiness/capability metadata to tenant roles; never render secret refs or
  profile destinations outside the platform-only workspace.
- Add actionable connector empty states that explain which platform grant is missing while keeping
  source creation and egress behind all existing gates.
- Add matched allow/deny, forged-parent/tenant, redaction, immutable-version, audit, PostgreSQL, and
  browser evidence; update current-behavior and planning records; archive and commit.

## Non-goals and approval boundaries

- No new role/capability, authentication flow, directory-account/global-admin creation, public API,
  dependency, schema migration, credential value, secret persistence, or network-policy change.
- No profile deletion or grant revocation; disable preserves immutable lineage.
- No live external provider/connector call. Profile registration does not authorize egress by
  itself; existing grants, deployment flags, allowlists, source gates, and runtime gates remain.

## Trust boundaries and authorization

Scenario/document-set visibility is non-authoritative. Every mutation re-resolves persisted exact
parents and invokes the existing artifact/profile/grant service. Artifact authoring requires exact
scenario author authority. All profile/grant operations require persisted platform-admin authority;
tenant admins cannot self-provision destinations. Foreign and same-tenant unassigned parents are
non-disclosing. Browser confirmation and hidden controls are usability only.

## Data and operational impact

No schema change. New immutable artifact/profile revisions, status-only profile disables, explicit
grants, and redacted audit events are expected. Secret references are accepted only where the
canonical platform schema requires them, are never resolved or echoed, and remain platform-only.

## Implementation steps

1. Map existing artifact/profile/grant services, validators, models, routes, forms, audit events, and
   connector readiness behavior to the Part 4 acceptance criteria.
2. Implement exact scenario artifact authoring/versioning and contextual release readiness links.
3. Implement the platform-only setup inventory/forms/actions using existing audited services.
4. Add safe connector empty-state guidance without broadening source/egress authority.
5. Add focused and blast-radius tests, PostgreSQL/RLS and browser evidence, documentation, final
   staff/AppSec/SRE review, archive, commit, and continue to Part 5.

## Rollback

Revert console routes/templates/forms while retaining immutable rows and audit lineage. Disable any
synthetic test profiles through the existing status transition and deactivate synthetic identities.

## Risks

SSRF-enabling free-form destinations, secret disclosure, tenant self-provisioning, forged grants,
artifact schema bypass, lost immutable lineage, misleading readiness, stale-profile grant races,
and audit gaps. Mitigations are canonical validators, platform-only endpoints, trusted parent
resolution, central services, row locks, redacted rendering/audit, POST/CSRF, exact-role tests, no
live egress, and bounded form inputs.

## Status

Implemented and verified 2026-08-01. See `verification.md`.
