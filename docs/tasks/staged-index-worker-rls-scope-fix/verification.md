# Verification: staged-index-worker-rls-scope-fix

## Status

Implemented and repository-verified on 2026-08-31. Production/OpenShift deployment, authenticated
browser recovery, real external embedding-provider smoke, and production app-role grant execution
remain operator rollout gates. This record distinguishes operator-provided live evidence from
commands executed against the local/disposable verification environments.

## Live OpenShift evidence supplied by the operator on 2026-08-31

- `run_staged_index_build_job` repeatedly failed with
  `ArtifactVersion matching query does not exist`.
- The exact failing expression was
  `chunking_profile=job.chunking_profile` in `apps/ingestion/tasks.py`.
- Failed `StagedIndexBuildJob` rows `id=1` and `id=3` had
  `organization_id=1`, `embedding_profile_id=1`, and `chunking_profile_id=4`.
- `ArtifactVersion(id=4, organization_id=1, type=chunking_profile)` existed physically.
- A worker-local read-only query inside `transaction.atomic()` plus
  `set_tenant_context(1)` returned `artifact_visible_with_scope=True`.

The main agent did not access the live cluster and therefore records these as operator-supplied
evidence, not independently executed commands.

## Repository inspection performed during planning

| Evidence | Result |
| --- | --- |
| `apps.tenancy.context.set_tenant_scope` | Requires an atomic block and uses transaction-local `set_config(..., true)` |
| `claim_build_job` | Installs exact tenant context inside a short transaction, loads only `document_set_version__document_set`, and returns after scope expiry |
| `run_staged_index_build_job` | Evaluates lazy profile relations after claim returns and does not establish a surrounding tenant transaction |
| `StagedIndexBuildJob.chunking_profile` | Protected FK to immutable `ArtifactVersion`, `on_delete=PROTECT` |
| RLS inventory/migration | `artifacts_artifactversion` is a direct-tenant FORCE-RLS protected table |
| Local Compose database role | Web/workers/migrations all use the PostgreSQL bootstrap owner `agenthub` |
| OpenShift role contract | Runtime role is separately provisioned `NOSUPERUSER ... NOBYPASSRLS`; migration role is separate |
| Existing repository verification | Records that local/CI owner execution bypasses RLS and can hide non-owner failures |

Planning inspection commands included bounded reads/searches of:

- `apps/ingestion/tasks.py`
- `apps/ingestion/job_lifecycle.py`
- `apps/ingestion/staged_build.py`
- `apps/ingestion/models.py`
- `apps/tenancy/context.py`, middleware, RLS inventory, and RLS migration
- `deploy/compose/docker-compose.yml`
- `deploy/postgres/provision-app-role.sql`
- OpenShift install templates/scripts and existing ingestion lifecycle documentation

## Planning checks

| Check | Result |
| --- | --- |
| `git diff --check` after initial plan/threat-model creation | Passed |
| Code changes | None |
| Tests | Not run; planning-only task state |
| Live production mutations | None by the main agent |

## Implementation-start revalidation (2026-08-31)

- Live local Compose state was queried from `deploy/compose/docker-compose.yml`: PostgreSQL, Redis,
  MinIO, web, ingestion/runtime/eval workers, and beat were running; infrastructure healthchecks
  were healthy and `/v1/health/live` returned HTTP 200.
- `check_ingestion_preflight --require-worker` passed with contract revision 2 and a compatible
  worker. The recorded configuration fingerprint was intentionally not copied here.
- Codebase Memory located the durable task/build/lifecycle call graph. Its index-status discovery
  tool and Serena were not available in this session, so graph output was treated only as navigation
  evidence and reconciled against direct source/policy inspection.
- The active handoff was stale for this incident and was not trusted; live status, source, task
  records, Compose topology, and readiness were re-read.
- `deploy/postgres/provision-app-role.sql` and the Helm PostgreSQL initializer grant the runtime
  application role schema `USAGE`, not schema `CREATE`. `apps/ingestion/vector_store.py` performs
  runtime per-index table/index/policy creation and table drop directly. This is a deterministic
  post-scope-fix production blocker and requires a separately approved least-privilege DDL seam.

## Why existing RLS tests did not catch the incident

Repository search found at least 13 test files that explicitly create/use non-owner PostgreSQL
roles (`NOSUPERUSER`/`NOBYPASSRLS` or the equivalent default) and switch role to prove FORCE-RLS
behavior. Therefore the RLS test inventory is not universally owner-bypassed.

The uncovered gap is compositional:

- `apps/ingestion/tests/test_job_lifecycle.py::test_job_and_outbox_force_rls_under_non_owner`
  proves empty/wrong/correct scope visibility and FORCE RLS for the durable job/outbox tables, but
  does not execute the worker task or traverse artifact FKs under that role.
- `apps/ingestion/tests/test_rls.py` proves FORCE RLS for the per-index vector store under a
  non-superuser role, independently of the durable worker lifecycle.
- `apps/ingestion/tests/test_staged_build.py` exercises parsing, embedding, vector persistence, and
  retrieval on PostgreSQL, but the normal local PostgreSQL connection is the bootstrap owner and the
  test calls `build_staged_index` directly rather than through `run_staged_index_build_job`.
- No existing test combines the production conditions: a non-owner app role, transaction-local
  scope, a durable job with a required tenant-owned chunking artifact, claim transaction expiry,
  and subsequent task argument/lifecycle execution.

The default pytest configuration uses in-memory SQLite, where tenant-scope installation is a
validation-only no-op and PostgreSQL RLS tests are skipped. PostgreSQL suites remain valuable but a
broad owner-backed run cannot replace the missing non-owner end-to-end worker regression.

## Repository-wide same-pattern audit (2026-08-31)

This was a read-only source/policy/test audit. No production task was executed and no database role
was changed. A path is classified as **confirmed** below only where the protected table has FORCE
RLS and the source performs the query after the transaction-local tenant scope has expired, or
without installing a tenant scope at all. These findings are separate from the operator-proven
staged-build incident and require separately approved implementation scope.

| Priority | Path | Confirmed behavior under the non-owner runtime role | Existing test gap |
| --- | --- | --- | --- |
| P0 | `apps/ingestion/tasks.py::run_staged_index_build_job` | Operator-proven lazy `ArtifactVersion` FK read after `claim_build_job` commits raises `DoesNotExist` | No non-owner end-to-end durable worker test |
| P0 | `apps/ingestion/tasks.py::build_document_set_index_task` | Loads objects in a scoped transaction, then calls `build_staged_index` after scope expiry; the build's protected grant/index/document queries fail closed | Task test runs on the ordinary owner/SQLite path and only covers an already-existing index |
| P0 | `apps/ingestion/automation.py::apply_connector_automation` | Returns schedule/candidate from a scoped transaction, then performs publish, refresh, index, binding, release, and artifact queries outside scope. `draft_only` avoids most of the affected path; staging/promotion modes do not | Automation tests execute on SQLite/owner; independent connector RLS tests do not run the automation lifecycle under a non-owner role |
| P0 | `apps/workflows/tasks.py::execute_unified_run_branch` | After scoped claim/execution/completion, the task queries FORCE-RLS `RunBranch` outside a tenant transaction. It receives `None`, returns `missing`, and skips join/resume/background redispatch | Parallel workflow task tests run on SQLite/owner; workflow RLS tests prove table isolation separately, not task convergence under the role |
| P1 | `apps/observability/tasks.py::report_retention_backlog` and `apps/observability/retention.py::run_retention` | Global report/purge querysets for FORCE-RLS `Run`, `RunBranch`, and `RunWait` install no tenant scope. Under the non-owner role they can report/purge zero rows silently | Retention tests use SQLite/owner and contain no non-owner or per-tenant traversal case |

The durable background-run executor in `apps/workflows/tasks.py::execute_unified_background_run`
does not show this defect in the inspected path: its claim, transition, wait, and bounded executor
helpers establish their own tenant-scoped atomic boundaries. Likewise the Confluence/REST sync task
post-processing reads only scalar fields loaded inside its scoped transaction, and the sync service
phases install their own scope. These are not a substitute for a non-owner integration gate, but
they were not classified as confirmed findings in this audit.

### Management-command exposure

The same deployment-only assumption is broader in operator commands. The following representative
commands query FORCE-RLS tenant rows before installing a scope, so the non-owner OpenShift runtime
role can return `not found`, an empty list, or skip work even when rows exist:

- ingestion build/start/retry/REST sync/Confluence sync commands;
- artifact export and validation commands;
- release compile/eval/promote/rollback/canary commands;
- tool approval list/decision/cancellation commands; and
- runtime-resume redispatch of queued `Run` rows.

This command class is not always the identical lazy-FK failure, but it has the same root contract
violation: production code assumes owner visibility instead of opening a trusted, bounded tenant
transaction. `promote_staged_index` is a useful counterexample: it explicitly enumerates bootstrap
organizations and installs each candidate tenant scope inside one atomic resolution boundary.

### Required follow-up ownership

1. Keep the staged-index durable worker fix as the incident P0.
2. Create a separate P0 tenant-scope task covering legacy build and connector automation; do not
   fold connector/release authorization changes silently into the ingestion incident patch.
3. Create a separate P0 workflow task for branch post-completion convergence.
4. Create a P1 retention task that defines explicit authorized tenant enumeration and preserves
   bounded transactions/audit semantics.
5. Create a P1 management-command hardening task with a shared organization-resolution pattern and
   non-owner command tests. Do not solve it by using the migration role or granting `BYPASSRLS`.

## Evidence required after implementation

- A red-before/green-after PostgreSQL test reproducing the exact lazy-FK failure under a provisioned
  non-owner FORCE-RLS role.
- Same-tenant success and missing/wrong/cross-tenant denial for every build input and lifecycle
  phase.
- Proof that external object-store/provider calls do not execute inside a transaction spanning the
  whole build and that progress/heartbeat commits remain visible.
- Duplicate delivery, cancellation/late result, retry, ambiguous outcome, and reconciliation tests.
- Real worker/Redis/object-store/embedding/pgvector smoke in a staging-equivalent environment.
- Safe error/log/audit/metric redaction evidence.
- Required formatter, linter, type, backend, PostgreSQL/RLS, security, migration, secret, browser,
  rollout, and rollback evidence from the final tree/image.

## Implementation evidence (2026-08-31)

### Red-before / green-after root-cause proof

Before the fix, the new durable-worker PostgreSQL test committed the claim transaction, switched to
a `NOSUPERUSER NOBYPASSRLS` role, and reproduced the incident at the same expression:
`ArtifactVersion.DoesNotExist` while evaluating `job.chunking_profile`. After the fix, the actual
bound `run_staged_index_build_job` completes with the pinned chunking artifact, a succeeded durable
job, and an exact promotable result under that role.

The claim now locks only the job row, eagerly loads all protected pinned artifact relations inside
the exact tenant transaction, and validates document-set/artifact organization and artifact type.
Build helpers use short tenant-scoped transactions for grants, parent lookup, index creation,
bounded membership/version materialization, parsed metadata, finalization, and failure. A provider
boundary test observed `connection.in_atomic_block == False` during embedding.

### Least-privilege DDL evidence

Migration `ingestion.0015_index_store_ddl_functions` was applied both to fresh PostgreSQL test
databases and the preserved local Compose database. Its two migration-owner functions:

- accept only an integer `IndexVersion` identity and derive `chunk_iv_<id>` internally;
- pin `search_path`, re-resolve exact tenant/lifecycle/type/dimensions, and revoke `PUBLIC`;
- leave schema `CREATE`, relation ownership, superuser, and `BYPASSRLS` unavailable to runtime;
- grant only created-store `SELECT`/`INSERT` and sequence use to the directly authenticated session
  role; and
- refuse wrong tenant scope, non-building provision, and active-store retirement.

The non-owner test verified `rolsuper=false`, `rolbypassrls=false`, no schema `CREATE`, no inherited
function execution before the explicit grant, wrong-scope denial, correct-scope provision/drop,
and active-store drop denial. Database details are normalized to allowlisted content-free
`VectorStoreError` codes.

### Commands and results

| Check | Result |
| --- | --- |
| Final full repository SQLite profile, detailed pytest output | `1309 passed, 65 skipped` in 651.12s; skips are PostgreSQL/pgvector/RLS/locking-specific |
| Final PostgreSQL ingestion profile, detailed pytest output | `154 passed, 2 skipped` in 139.70s; the skips are the off-PostgreSQL guard assertions |
| Focused PostgreSQL worker/vector/build/RLS profile | `35 passed, 2 skipped` before the final added lifecycle case; final full profile includes all 156 collected cases |
| Final non-owner/DDL-lifecycle/provider boundary recheck | `4 passed` in 53.39s; both fixed-name `NOLOGIN` probe roles were removed and a cluster-level query returned no residue |
| Ruff format | `474 files already formatted` |
| Ruff lint including Bandit-style rules | `All checks passed!` |
| Mypy with `PYTHONPATH=/app` and `requirements.lock` tool versions | `Success: no issues found in 474 source files` |
| Django system check | `System check identified no issues` |
| Migration drift | `No changes detected` |
| Compileall | Passed |
| `git diff --check` | Passed |
| Frontend build from canonical local-stack wrapper | TypeScript check and Vite build passed; no frontend source changed |

The host Python launcher failed before Python startup with the documented Windows logon-session
error. Per `docs/manual-testing-guide.md` section 0.1, tests/checks ran in the disposable Python
3.13 container `agenthub-staged-index-test` against the canonical Compose PostgreSQL/pgvector
service. Development-only ruff/mypy/django-stubs were installed only in that disposable container;
repository dependencies were unchanged.

### Current-image local runtime evidence

The non-destructive `scripts/local-stack.ps1` update preserved PostgreSQL/MinIO volumes, built the
current frontend/application image, applied migration `0015`, and recreated all application roles.
After rollout:

- all web/runtime/ingestion/eval/beat roles were running and infrastructure healthchecks were green;
- `/v1/health/live` returned HTTP 200;
- `check_ingestion_preflight --require-worker` returned `contract=3` and
  `compatible_worker=yes`; and
- bounded web/ingestion logs contained no `ERROR`, traceback, `DoesNotExist`, or index-store error.

### Browser gate

The current local image redirected logged-out `/console/` access to
`/console/login/?next=/console/`, rendered the expected local operator login controls, and emitted
no browser console warnings/errors. Authenticated document-set/build/retry verification was not
performed because no existing local credential was available and changing/seeding an operator
credential would be an unrelated authorization mutation. This remains a named manual rollout gate,
backed by the full console tests in the repository suite.

### Checks marked not applicable or not executed

- Dependency vulnerability scan: N/A to the diff; no production dependency changed.
- Secret scan: no secret-bearing file or credential changed; ruff security rules and final diff
  inspection found no embedded secret. A dedicated secret-scanner executable was not available.
- Reverse migration execution: not run against the retained local database because it would remove
  a function currently used by the updated local worker. Reverse code was inspected; it removes
  only the two functions and deliberately leaves store tables/data.
- Real external provider smoke: not run; it requires deployment credentials, endpoint approval,
  provider cost authority, and an authenticated document-set operator.

## Final review

- **Staff engineer:** the change is bounded to durable staged builds and the required DDL seam;
  confirmed legacy/automation/workflow/retention/command findings remain in the separately owned
  `background-rls-entrypoint-hardening` task.
- **Application security:** FORCE RLS and exact tenant context remain mandatory; no authorization
  predicate was relaxed. The privileged functions expose no caller-controlled identifier, type, or
  SQL fragment and revoke `PUBLIC`.
- **SRE:** worker contract revision 3 prevents mixed-worker readiness; rollout order is migration,
  app-role grant reapplication, worker drain/replacement, preflight, then one authorized retry.
  Rollback stops revision-3 workers before reversing the functions.
