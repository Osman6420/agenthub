# Phase 2 RLS deployment readiness

`check_tenant_rls` is a read-only pre-deployment diagnostic for the PostgreSQL invariants in
[ADR-0004](../adr/0004-tenant-isolation-postgres-rls-connection-context.md). It inventories installed
Django models and checks a separately provisioned application role:

```powershell
python manage.py check_tenant_rls --app-role agenthub_app
```

The command does not create or alter roles, grants, policies, tables, connections or tenant
context. Run it through a migration/read-only administrative connection that can inspect PostgreSQL
catalogs; `--database` and `--schema` select an already-configured Django connection and a
lower-case PostgreSQL schema. Do not put a password or connection string in command arguments.

The inventory classifications are:

- `protected`: a required direct `organization_id` column exists and ADR-0004 RLS checks apply;
- `indirect`: tenant ownership is reachable only through another table and is a rollout blocker;
  P11.2 removed all current indirect classifications by adding direct lineage;
- `bootstrap`: organization membership resolves an operator's trusted scope and needs a separate
  bootstrap/access design;
- `telemetry`: nullable cross-plane audit/usage data needs a separate append/admin access design.

Readiness fails if the proposed role is absent, superuser, `BYPASSRLS`, owns a protected table,
lacks required read access, or if a protected table lacks enabled+forced RLS and the exact
canonical `tenant_isolation` policy. It also fails while any `indirect` model remains. A passing
result proves catalog configuration only: it does not prove web/worker tenant-context propagation,
pool isolation, platform-admin access, migration ownership, or production rollout approval.

The command remains diagnostic. It currently expects 47 protected direct-tenant tables plus the
documented bootstrap/telemetry exceptions. Do not use a failing result as a reason to
disable RLS, broaden a role, connect the application as the table owner, or grant `BYPASSRLS`.
P11.1 does not require blanket insert/update/delete grants; define those per table in the later
least-privilege role design, especially for immutable and append-only records.
