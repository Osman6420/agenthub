# Task Plan: staged-index-worker-rls-scope-fix

## Task summary

Fix the durable staged-index ingestion worker so every PostgreSQL access executes under the exact
transaction-local tenant scope while object-store, embedding, OCR, and other remote calls execute
without holding one long database transaction open. Preserve FORCE RLS, the non-owner application
role, immutable profile lineage, durable job semantics, and separate index-promotion authority.

## Background

The 2026-08-31 OpenShift incident produced repeatable
`ArtifactVersion.DoesNotExist` failures while evaluating
`job.chunking_profile` in `run_staged_index_build_job`. Read-only production evidence established:

- the failed `StagedIndexBuildJob` rows exist and reference `chunking_profile_id=4`;
- `ArtifactVersion(id=4, organization_id=1, type=chunking_profile)` exists;
- the artifact is visible when `set_tenant_context(1)` is installed inside `transaction.atomic()`;
- `claim_build_job` installs that transaction-local scope but returns the job after the transaction
  closes; and
- the task then lazy-loads tenant-protected profile relations with an empty scope, so FORCE RLS
  returns no row and Django raises `DoesNotExist`.

Local Compose did not reproduce this because every application role uses the PostgreSQL bootstrap
owner (`agenthub`). Repository verification already records that the local/CI owner bypasses RLS.
OpenShift correctly uses a separately provisioned `NOSUPERUSER NOBYPASSRLS` runtime role. The
environment difference exposed an application defect; OpenShift, Helm, the uploaded document, and
the artifact row are not the root cause.

## Scope

- Durable `run_staged_index_build_job` claim, input loading, build, progress, completion, failure,
  retry, and reconciliation paths.
- Tenant-protected ORM access performed by `build_staged_index` and its direct helpers.
- Safe error classification for expected ingestion, storage, parser, embedding, OCR, vector-store,
  and tenant-scope failures.
- Non-owner PostgreSQL/FORCE-RLS integration coverage using the provisioned app-role contract.
- A repository-wide read-only audit of Celery/background/management-command entry points that touch
  protected tables, looking for transaction-local scope expiry, lazy ORM access, and owner-only
  test coverage. Same-pattern findings must be fixed in approved scope or recorded as separate
  owned tasks before this incident is closed.
- Operational rollout, failed-job recovery, monitoring, and a bounded emergency workaround review.
- Current-behavior and operator troubleshooting documentation affected by the fix.

## Confirmed related findings and remediation workstreams

The repository-wide audit confirmed that the incident is one instance of a broader background and
operator-entry-point contract gap. The workstreams below are part of the remediation programme, but
must remain separately reviewable changes unless the owner explicitly approves a combined diff.

| Priority | Workstream | Confirmed defect | Delivery boundary |
| --- | --- | --- | --- |
| P0 | Durable staged-index worker | `run_staged_index_build_job` evaluates protected profile FKs after `claim_build_job` commits and its transaction-local scope expires | This task's primary implementation |
| P0 | Legacy build and connector automation | `build_document_set_index_task` calls the build after scope expiry; `apply_connector_automation` performs publish/index/binding/release/artifact work after returning objects from a scoped transaction | Separate tenant-scope task and diff; share the non-owner worker test fixture |
| P0 | Parallel workflow convergence | `execute_unified_run_branch` queries FORCE-RLS `RunBranch` outside scope after branch completion, can return `missing`, and can skip join/resume/redispatch | Separate workflow-owned task and diff |
| P1 | Retention reporting and purge | Global `Run`/`RunBranch`/`RunWait` querysets install no tenant scope and can silently report or purge zero rows under the runtime role | Separate observability task defining bounded authorized tenant enumeration |
| P1 | Management-command hardening | Representative ingestion, artifact, release, tool-approval, and runtime-resume commands resolve protected rows before installing scope | Separate cross-component command-hardening task with a shared resolution pattern |

Paths inspected but not classified as confirmed failures include the bounded unified background-run
executor and Confluence/REST sync service phases: their relevant helpers establish tenant-scoped
atomic boundaries, and the sync tasks retain only already-loaded scalar identifiers after commit.
They still require coverage in the reusable non-owner integration gate.

## Non-goals

- Disabling or weakening FORCE RLS, changing its policy expression, or granting `BYPASSRLS`.
- Giving workers the migration/owner database role or using session-wide tenant context.
- Changing organization, document-set, profile-grant, build, retry, cancellation, or promotion
  authorization contracts.
- Changing embedding endpoints, credentials, vector geometry, parser behavior, or public APIs.
- Deleting failed jobs, failed indexes, artifact lineage, audit evidence, or uploaded documents.
- Adding a production dependency. The owner separately approved the additive privileged-function
  migration after implementation discovery proved the non-owner DDL blocker.

## Acceptance criteria

1. A durable staged-index job with a same-tenant chunking profile runs to a promotable index under a
   real `NOSUPERUSER NOBYPASSRLS` PostgreSQL application role.
2. Chunking, retrieval, summary-model, summary-prompt, OCR, embedding-grant, document membership,
   index, progress, failure, completion, retry, and reconciliation accesses use the exact trusted
   organization scope; missing or foreign scope fails closed.
3. Celery receives identifiers and trusted organization metadata only; it does not accept client-
   supplied profile, tenant, endpoint, credential, or authorization decisions.
4. Object-store reads and embedding/OCR/model network calls do not run inside one transaction that
   spans the whole build.
5. Progress and heartbeat updates commit independently and remain observable during a long build.
6. Duplicate delivery and retry converge without duplicate active indexes or widened scope.
7. Existing failed jobs remain durable. After deployment, an authorized retry creates or links only
   the exact same-tenant, same-profile pipeline result allowed by the lifecycle contract.
8. Expected safe failures retain stable content-free error codes rather than collapsing into
   `BUILD_INTERNAL_ERROR`; secrets, endpoints, document text, embeddings, and raw provider bodies
   remain absent from logs/audit/UI.
9. SQLite regression remains green, but completion additionally requires focused and repository-
   applicable PostgreSQL/pgvector tests with a non-owner FORCE-RLS role.
10. No migration, public API, authorization-contract, dependency, or deployment-role change occurs
    without explicit owner approval and a plan update.
11. Every background task that accesses FORCE-RLS protected tables is inventoried with its trusted
    tenant source, transaction boundary, lazy-load risk, and non-owner test evidence; unresolved
    same-pattern risks have explicit owners and follow-up plans.

## Affected components

- `apps/ingestion/tasks.py` (unchanged identifier-only task contract; behavior verified end to end)
- `apps/ingestion/job_lifecycle.py`
- `apps/ingestion/staged_build.py`
- Direct build helpers in parsing, document storage/metadata, summaries, embedding, OCR, and vector
  storage where they cross a database/external-I/O boundary
- `apps/ingestion/tests/` and applicable tenancy/PostgreSQL integration fixtures
- Ingestion operations/manual-testing documentation
- Potentially the ingestion lifecycle ADR only if the existing durable contract does not already
  specify short transaction boundaries
- Follow-up ownership, without silently expanding this implementation diff:
  - `apps/ingestion/automation.py` and the legacy build task in `apps/ingestion/tasks.py`
  - `apps/workflows/tasks.py` parallel branch convergence
  - `apps/observability/tasks.py` and `apps/observability/retention.py`
  - tenant-aware management commands across ingestion, artifacts, releases, tools, and agents

## Interfaces affected

No public HTTP or Celery payload contract changed. Internal worker contract revision increased from
2 to 3 so readiness rejects mixed old/new ingestion workers. The claim phase now eagerly resolves
and validates every pinned input under exact scope; later database phases use exact IDs and short
tenant-scoped transactions. The existing durable job remains the authority.

## Data impact

The additive migration creates two database functions and does not alter existing rows or physical
stores. Existing job, artifact, document, index, outbox, and audit rows remain intact. Failed jobs
are recovered only through the existing authorized retry and reconciliation lifecycle after the
corrected worker image is deployed.

## Security impact

The fix restores intended tenant-scoped execution without weakening defense in depth. Tenant scope
must derive only from the validated task header and authoritative job lineage. Every related object
is re-resolved or validated within that exact organization scope. Raw exception logging and any
workaround that exposes credentials, endpoints, content, or embeddings remain prohibited.

See [threat model](threat-model.md).

## Authorization impact

No authorization decision changes. Build/retry/cancel and promotion remain separate server-side
capabilities. Because implementation touches tenant-isolation enforcement, explicit owner approval
is required before code changes, followed by same-tenant, missing-scope, wrong-scope, and cross-
tenant negative evidence.

## Observability impact

- Preserve monotonic progress and heartbeat commits during external I/O.
- Add or refine stable, bounded failure classes for scope/input loading, storage, parsing,
  embedding, OCR, vector-store, and finalization failures.
- Keep tenant/job/document/endpoint identifiers out of metric labels.
- Correlate worker traceback, durable job, index failure, and audit events using existing safe
  request/job references; never log raw documents, embeddings, credentials, or provider bodies.

## Migration impact

Discovery found a second production blocker before implementation: the provisioned application
role has only `USAGE` on schema `public`, while `provision_store` and `drop_store` execute runtime
`CREATE TABLE`/`CREATE INDEX`/RLS-policy and `DROP TABLE` DDL. The non-owner OpenShift worker will
therefore fail at store provisioning immediately after the tenant-scope defect is fixed.

The owner approved the recommended least-privilege repair on 2026-08-31: an additive migration that installs migration-owner
`SECURITY DEFINER` functions for exact `IndexVersion`-derived `chunk_iv_<integer>` provisioning and
retirement. The functions must use a fixed `search_path`, validate the authoritative index row,
tenant scope, lifecycle state, dimension/index type, and system-generated relation name, and expose
only `EXECUTE` to the application role. Direct schema `CREATE`, table-owner, migration-role, or
`BYPASSRLS` privileges remain forbidden. Rollback must revoke execution and remove the functions only after
all workers using the new contract are stopped or rolled back.

## Dependencies

- Existing transaction-local tenant context in `apps.tenancy.context`.
- Existing FORCE-RLS policies and `deploy/postgres/provision-app-role.sql` non-owner role.
- Existing durable job/outbox/reconciliation lifecycle and pgvector per-index stores.
- Existing object-store, embedding, OCR, and summary provider bounds.

## Implementation steps

1. Add a failing PostgreSQL regression that dispatches/executes the durable build with a required
   chunking profile under the provisioned non-owner app role and reproduces the current lazy-FK
   `DoesNotExist` failure.
2. Inventory every ORM query and mutation from task claim through build success/failure, including
   lazy descriptors and helper calls. Classify each operation as a short DB phase or external I/O.
3. Audit other Celery/background/management-command entry points for the same scope-expiry pattern.
   Record protected tables, tenant authority source, transaction lifetime, post-transaction ORM
   objects/lazy relations, and whether a non-owner end-to-end test exists. Keep unrelated fixes out
   of this diff unless separately approved, but create owned follow-up task records for every
   confirmed exposure.
4. Introduce one worker orchestration boundary that accepts only `job_public_id` plus trusted
   `organization_id`. In an initial short tenant-scoped transaction, lock/claim the job, eager-load
   or explicitly resolve all pinned inputs, and validate exact organization/type/status/grants.
5. Represent validated immutable inputs using exact IDs and/or a typed in-memory snapshot so later
   argument evaluation cannot issue accidental unscoped lazy queries. Do not treat eager loading as
   the complete RLS fix.
6. Refactor build persistence into short tenant-scoped phases: preflight/lineage validation,
   compatible-parent lookup and index creation, bounded membership metadata loading, per-document
   metadata persistence, progress/heartbeat, finalization, and failure cleanup.
7. Keep S3/MinIO reads, parsing CPU work, embedding/OCR/model calls, and other remote I/O outside a
   transaction spanning the full build. Revalidate durable job/index state before each committing
   phase so cancellation, retry, redelivery, and late results remain safe.
8. Preserve per-index vector-store RLS and exact organization checks. Verify DDL/write/copy helpers
   install the correct scope in their own transactions and cannot copy across tenant, document set,
   geometry, or pipeline fingerprint.
9. Expand task exception mapping so known content-free operational codes survive while unexpected
   exceptions remain safely classified and traced. Preserve ambiguous-provider outcomes as
   reconciliation-required rather than blind retry.
10. Add recovery behavior/evidence for the incident's existing failed jobs: deploy compatible worker
   first, verify readiness, then use the authorized UI retry one job at a time; never edit FK/checksum
   fields or delete lineage as a workaround.
11. Update operator/current-behavior documentation, record exact verification commands/results, and
    review the final diff as staff engineer, application-security engineer, and SRE.
12. Before closing the incident, create and link the separately owned P0/P1 task records listed in
    **Confirmed related findings and remediation workstreams**. Each record must identify its
    authoritative tenant source, short transaction boundaries, authorization invariants, rollout,
    rollback, and non-owner PostgreSQL evidence. A finding may be closed only by a verified fix or
    an explicit documented risk acceptance; absence of a runtime exception is not evidence.

## Test plan

- Focused unit tests for build-input loading, no accidental lazy queries, safe exception mapping,
  progress monotonicity, retry bounds, cancellation, and late-result convergence.
- SQLite suite for compatibility and state-machine behavior; explicitly not accepted as RLS proof.
- PostgreSQL/pgvector tests under `NOSUPERUSER NOBYPASSRLS` for:
  - same-tenant chunking/retrieval/summary/OCR profile combinations;
  - empty and wrong tenant scope denial;
  - forged/mismatched task organization header;
  - foreign artifact/profile/job/document/index references;
  - cross-tenant vector reuse denial;
  - duplicate delivery, cancellation, retry, stale worker, and reconciliation;
  - progress/heartbeat visibility while provider work is still running; and
  - no external provider/object-store call inside a build-long transaction.
- A reusable non-owner app-role integration fixture/gate for background worker paths, plus an audit
  test or inventory assertion that prevents newly added protected-table Celery tasks from relying
  only on owner-backed coverage.
- Real-service smoke: upload a bounded text document, publish, build with a real tenant-granted
  embedding profile, obtain a promotable pgvector index, explicitly promote with the existing
  authority, and query through the authorized scenario path.
- Formatter, linter, type-check, Django checks, migration drift check, secret scan, focused security
  tests, repository-applicable backend suite, and mandatory browser authorization/UX gate.
- Verify logs/audit contain stable codes and correlation only, with no content, vectors, endpoints,
  credentials, or provider response bodies.

## Rollout plan

1. Obtain explicit approval for the tenant-isolation implementation.
2. Reproduce and verify the fix in a staging-equivalent environment using the same non-owner app
   role and FORCE-RLS provisioning as OpenShift.
3. Build a digest-pinned image and deploy ingestion worker first while preventing incompatible old
   ingestion workers from consuming the queue.
4. Run ingestion preflight and verify compatible heartbeat/config fingerprint.
5. Deploy web/beat components only if the internal contract revision changes; otherwise retain the
   smallest rollout.
6. Retry one retained failed job, observe progress/heartbeat, verify exact promotable lineage and
   safe logs, then continue bounded recovery.
7. Monitor failure-class counts, queue age, worker heartbeat, build duration, PostgreSQL transaction
   age/locks, object-store/provider errors, and duplicate/reconciliation outcomes.

## Interim operating guidance

Until a verified image is deployed:

- Operators may continue uploading bounded documents into a draft document-set version. Upload and
  object-store persistence are separate from staged-index execution; keep the draft unpublished if
  automatic preparation is configured.
- Do not start or retry staged-index jobs with the affected worker image. Repeated attempts consume
  the bounded attempt budget, add failed lineage/noise, and cannot repair the missing transaction
  scope.
- Existing uploaded bytes, drafts, artifacts, failed jobs, and failed indexes must be retained. They
  are recovery inputs and evidence, not corruption to delete.
- If publishing a draft can trigger `auto_prepare`, postpone publication until the corrected worker
  is ready or first follow an owner-approved procedure that safely disables automatic preparation
  without starting another build.
- There is no supported zero-risk, no-code path to a searchable/promotable index through the normal
  UI on the affected image.
- A direct one-off Django-shell build is technically possible by holding a tenant-scoped outer
  transaction, but it bypasses part of the durable job workflow and keeps a transaction open across
  storage/provider work. It is therefore an emergency production mutation, not the default
  workaround. It requires explicit production-change approval, a reviewed exact-ID runbook,
  bounded input, database transaction/lock monitoring, provider-cost approval, success/failure
  reconciliation, and a rollback decision before execution.
- Never work around the incident by changing `DATABASE_URL` to the migration role, granting
  `BYPASSRLS`, disabling/altering FORCE RLS, setting session-wide tenant scope, nulling or rewriting
  job FK/checksum fields, or deleting failed jobs/artifacts/indexes.

## Rollback plan

- Stop new build dispatch/retry and scale the incompatible ingestion worker down before rolling the
  image back.
- Preserve uploaded documents, jobs, outbox rows, failed/promotable indexes, artifact pins, and
  audit evidence.
- Do not retry jobs with an old worker known to reproduce the scope bug.
- If any result is ambiguous, move through the existing reconciliation-required/operator-review
  path; do not blindly replay external calls.
- Rollback stops revision-3 ingestion workers first, restores a compatible image/queue contract,
  then reverses migration `ingestion.0015`. Reversal removes only the privileged functions;
  existing per-index store tables and data remain intact. Reapply the reviewed app-role template
  matching the restored image after the migration state is settled.

## Risks

- One outer transaction around the entire build would hold a database transaction open across
  remote calls and hide progress/heartbeat commits; explicitly reject this as the durable design.
- Eager-loading only the current artifact relations may move the failure to the next RLS-protected
  query; require end-to-end non-owner tests.
- Splitting phases can introduce cancellation or input-state races; revalidate locked durable
  lineage before commits and retain idempotency constraints.
- Incorrect trusted-organization propagation could expose cross-tenant rows; derive it from the
  signed/internal task metadata and match it to the authoritative job on every phase.
- Overly broad logs added for diagnosis could disclose content, endpoints, or secrets; keep stable
  codes and safe identifiers only.
- Local owner-based tests can pass while production fails; a non-owner app-role gate is mandatory.
- Connector automation may appear healthy in `draft_only` mode while staging/promotion modes remain
  broken, so mode-specific non-owner coverage is required.
- Parallel branch execution may commit the branch result and then silently skip join convergence;
  recovery must be idempotent and must not execute branch/provider work twice.
- Retention can fail silently as a zero backlog rather than raising, so rollout evidence must seed
  known eligible rows and verify per-tenant counts under the real runtime role.
- A generic command wrapper can accidentally widen platform-admin visibility. Management commands
  must enumerate only bootstrap-visible organizations and open one explicitly authorized bounded
  tenant scope at a time; never install an unbounded/session-wide scope.

## Open questions

- Should the internal worker orchestration use a typed immutable snapshot or exact IDs reloaded per
  phase? Decide during implementation based on cancellation/freshness requirements.
- Does the existing lifecycle contract revision need to change if mixed old/new workers could
  consume the same durable job? Prefer a revision bump if compatibility cannot be proven.
- Is a one-off emergency build justified before rollout? Default is no. If business-critical, it
  requires separate production-change approval, one bounded document/set, a reviewed shell/runbook,
  transaction-age monitoring, exact lineage verification, and no RLS/role weakening.
- The additive least-privilege `SECURITY DEFINER` migration for per-index store provision/drop was
  approved on 2026-08-31. General schema `CREATE` remains an unacceptable fallback.

## Status

Verified in repository and the preserved local Compose environment; production rollout/manual
acceptance remains. Tenant-isolation implementation and the additive least-privilege
privileged-function migration were approved. No production/OpenShift mutation has occurred.

## Completion criteria

- Every acceptance criterion maps to recorded evidence in `verification.md`.
- Definition-of-Done security, authorization, privacy, observability, migration, operations, and
  browser gates are completed or explicitly marked N/A with justification.
- PostgreSQL non-owner/FORCE-RLS and real ingestion-worker evidence pass on the final image.
- Current behavior and operator recovery are documented; durable decisions are moved to an ADR if
  the existing ingestion lifecycle ADR is insufficient.
- Master plan is updated and this task is archived only after verified completion.
