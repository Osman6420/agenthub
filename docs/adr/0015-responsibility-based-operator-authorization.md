# ADR 0015: Responsibility-based operator authorization

- **Status:** Accepted
- **Date:** 2026-07-30
- **Supersedes:** [ADR-0013](0013-scoped-operator-capabilities-and-superadmin-recovery.md)

## Context

ADR-0013 introduced a central capability service and object-scoped assignments while retaining
one broad role on each organization membership. That staged model now has two competing authority
sources: organization roles and object responsibilities. Membership also grants broad read
visibility, and tool approval uses organization role strings even though each invocation already
belongs to an exact scenario.

The approval actor contract additionally compares a machine `Consumer.subject` string with a human
username for self-approval. Those values belong to different identity classes and namespaces.

All existing persisted application state is disposable demo data. The owner approved a clean
authorization redesign on 2026-07-30; legacy role/data compatibility is not required.

## Decision drivers

- Deny by default for reads and writes at exact tenant/object scope.
- Represent affiliation separately from authority.
- Make every human privilege explicit, reviewable, revocable and auditable.
- Preserve database foreign-key and RLS enforcement.
- Keep administrative, protected-content and approval authority separate.
- Use typed human and machine identities.
- Avoid an externally configurable policy language or custom-role engine.

## Considered options

1. Keep membership roles and add more exceptions/assignments.
2. Store arbitrary capability grants in one generic polymorphic table.
3. Use roleless membership plus a closed responsibility vocabulary and typed scope assignments.

## Decision

Use option 3.

`OrganizationMembership` records tenant affiliation and lifecycle only. Membership permits the
safe organization shell; it grants no project, scenario, document-set, audit, runtime or approval
authority.

Human authority is represented by typed platform, organization, project, scenario and document-set
responsibility assignments. Each assignment references the exact membership where tenant-bound,
uses a closed responsibility valid for its scope, retains lifecycle/provenance, and participates in
PostgreSQL FORCE RLS. A single central service maps responsibilities to closed capabilities and
returns the exact assignment authority source.

Organization and global administrators may manage authorized scopes but receive neither protected
document content nor tool approval implicitly. Project administrators may delegate scenario
viewer/editor responsibility only. Scenario approval, release and runtime responsibility require
explicit organization-administrator grants. Scenario-to-document-set retrieval remains a
two-sided authorization.

Tool approval always requires an active exact `scenario_approver` assignment. Tool artifacts cannot
select organization roles. Machine consumer identity remains on the invocation; an optional
verified human initiator and the human decider are stored as typed user references. Self-approval
denial applies only when the same verified human initiated and attempts to decide the request.

The daily global administrator and each organization's last administrator cannot expire. Django
superuser remains a separately audited recovery identity.

## Security consequences

- Membership no longer discloses all same-tenant object metadata.
- Authority is exact, additive and deny-by-default.
- Revoked membership is a top-level deny for every assignment.
- Approval is scenario-scoped and no longer policy-string widened.
- More explicit read capabilities and query filters are required; missing one is a disclosure risk.
- Mixed old/new authorization code or workers are forbidden at cutover.

## Operational consequences

Assignments increase administrative records and can leave a scenario without an active approver.
Readiness surfaces must report that condition without widening authority. Grant/revoke and
last-admin changes require row locks and required audit persistence.

The cutover uses the repository's confirmed disposable local `Fresh` reset only after clean
migration/seed evidence and exact-target confirmation. There is no production/in-place migration.

## Data and privacy consequences

Assignment and audit records contain safe identifiers and provenance, not protected content.
Approval queues expose only exact authorized scenario metadata and redacted input. Consumer
subjects and usernames are never treated as interchangeable identifiers.

## Migration impact

No role or assignment backfill is performed. Destructive migrations remove membership roles,
legacy assignment/owner fields and role-string approval fields. Migration history remains; a
clean database is recreated and seeded with roleless memberships plus explicit responsibilities.

## Rollback considerations

Rollback is previous code plus recreation of an empty disposable database/object store and the
previous seed. In-place downgrade or mixed worker fleets are unsupported. No authorization control
may be restored by widening RLS or adding a permissive fallback.

## References

- [Task plan](../tasks/scoped-operator-responsibility-authorization-redesign/plan.md)
- [Threat model](../tasks/scoped-operator-responsibility-authorization-redesign/threat-model.md)
- [ADR-0001](0001-custom-console-ldap-auth.md)
- [ADR-0004](0004-tenant-isolation-postgres-rls-connection-context.md)
