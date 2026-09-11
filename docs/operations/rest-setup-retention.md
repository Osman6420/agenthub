# Expired REST setup maintenance

The private setup checkpoint is reopenable for 30 days from its original creation.
Saving it again does not extend that deadline. Successful setup already removes the
duplicate mapping/input payload. Expired, unfinished checkpoints remain inaccessible
even before maintenance runs.

`purge_expired_rest_setups` clears the payload and free-text name of expired,
unfinished checkpoints in one explicitly selected organization. It preserves their
UUID, owner, organization, document set, original expiry, incremented revision and
purge timestamp. Completed source receipts, active drafts, sources, connections,
grants, documents and jobs are unchanged. It does not contact providers.

Apply migration `ingestion.0036_rest_setup_retention` before using this command. The
nullable marker preserves old payloads during migration; the partial queue index
supports bounded expiry scans. Plan normal migration/write coordination for index
creation on a large existing table. Use the PostgreSQL table owner's deployment
identity, not the ordinary application role. The server verifies database identity;
`--actor` is an audit label and cannot confer authority.

Preview a maximum of 100 eligible records (no names or payloads are printed):

```powershell
.venv\Scripts\python.exe manage.py purge_expired_rest_setups --organization-id <ORG_ID> --actor <OPERATOR_LABEL>
```

After reviewing the organization, preview count and authorized retention operation,
explicitly apply that batch:

```powershell
.venv\Scripts\python.exe manage.py purge_expired_rest_setups --organization-id <ORG_ID> --actor <OPERATOR_LABEL> --batch-size 100 --apply
```

Cleared content cannot be restored by this command. Each invocation handles one
batch of 1–500 records; the JSON report contains `candidates`, `purged`, and
`has_more`. Repeat an authorized batch while `has_more` is true. A later retry skips
already cleared records. No all-organization mode or automatic scheduler is added;
the deployment operator owns maintenance cadence and backup retention separately.

The operation locks organization then drafts, matching setup save/complete order.
It uses PostgreSQL time and never loads private payloads into the maintenance
result. Cleanup and `rest_setup_draft.payload_purged` audit events commit together;
an audit/database failure rolls back the whole batch. Audit events contain the
operator label, organization, target UUID, old/new revision and shared request ID.
Lock and statement limits produce the safe `REST_SETUP_RETENTION_DATABASE_UNAVAILABLE`
error; inspect deployment database health/content-free operational diagnostics before
retrying. No partial successful count is returned on failure.

SQL and ORM guards prevent purged records from being refilled or altered. SQL also
rejects early clearing, fabricated purge markers on insertion and purge updates
from a non-owner app role. Historical rollback before any purge is supported; once
purge evidence exists, reverse migration fails closed to preserve that evidence.
Use a reviewed forward fix instead of deleting receipts or disabling guards.

Implementation and synthetic PostgreSQL evidence are in the single
[AgentHub task](../tasks/Agent_Hub_MD/plan.md). No existing application data was
purged as part of implementation verification.
