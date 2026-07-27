# Phase 2 non-owner application-role rollout

The reviewed templates are [`provision-app-role.sql`](../../deploy/postgres/provision-app-role.sql)
and [`rollback-app-role.sql`](../../deploy/postgres/rollback-app-role.sql). They require `psql`
variables `app_role` and `database`; credentials remain in the deployment secret/IAM layer.

Rollout order:

1. Apply application migrations with the existing migration-owner connection. This adds direct
   tenant lineage and FORCE RLS policies but does not create a login role.
2. Run the provisioning template as the database owner in staging. Configure the login secret or
   certificate separately, then run `check_tenant_rls --app-role <role>`.
3. Start one web and one worker canary with the non-owner `DATABASE_URL`. Prove unauthenticated
   health, operator multi-membership scope, consumer singleton scope, worker singleton scope,
   missing/wrong context denial and connection reuse without scope leakage.
4. Drain old owner-role web/worker connections before scaling the non-owner deployment. Migration
   jobs retain the owner connection; web/worker pods never receive it.
5. Roll back by routing traffic away, restoring the previous application secret only under an
   approved emergency change, draining connections, and running the rollback template. The role is
   disabled and grants are revoked but it is not dropped automatically.

The grant matrix is intentionally table-specific. Immutable and append-only rows receive no
update/delete grant; platform profile catalogs are read-only; explicit draft/document lifecycle
tables retain delete only where current services expose an authorized delete/purge operation.
Bootstrap identity tables remain outside tenant RLS and therefore require especially narrow
queries, parameterization and application authorization.

Authorization-bearing tables are deliberately held at `SELECT, INSERT, UPDATE` with **no** `DELETE`:
the document-plane `documents_scenariodocumentsetaccessrequest` and
`documents_scenariodocumentsetgrant`, and the delegated operator assignments
`identity_projectadministratorassignment`, `identity_scenarioeditorassignment` and
`identity_documentsetmanagerassignment`. Revocation on all five is a status change that records
`revoked_by`/`revoked_at`, so who held which authority stays reconstructable from the table itself
rather than only from the audit trail, and a compromised application role cannot erase that evidence.
Granting `DELETE` on any of them would silently weaken that property and must not be done to work
around an application error; a missing privilege here fails closed and should be diagnosed instead.

Before deploying the worker signature change, drain or explicitly discard old workflow, agent and
ingestion messages that do not carry `organization_id`. Workflow/agent handlers treat a legacy
message as a safe no-op under the non-owner role; ingestion rejects the obsolete signature. Runtime
workflow/agent execution opens a bounded transaction around the execution phase so transaction-local
scope remains available to tool/event queries; monitor transaction age against the pinned runtime
deadline and abort rollout if it exceeds the operational threshold.
