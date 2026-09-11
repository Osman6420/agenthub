# Database architecture review — verification

Date: 2026-09-08. Baseline: `feat/foundation-sprint-0-1`, HEAD `2c3e959` plus the existing working-tree changes. This review does not certify that whole working tree. Application files and migration 0016 were already modified/untracked on arrival and were inspected without alteration.

## Executed evidence and results

1. `git status --short`, `git branch --show-current`, `git rev-parse --short HEAD`: recorded the dirty working tree and baseline; no checkout, reset or commit.
2. `Get-Content` on root AGENTS, engineering rules, task README/templates, handoff, archive policy and master plan: established review, planning, ownership and live-inspection requirements. The handoff was not used as runtime truth.
3. Tool metadata search for Codebase Memory/index status/Serena/tool-search: no applicable callable code-intelligence tool available. Used Django metadata, `rg`, AST/direct source and migration inspection instead. No graph was assumed fresh and no indexing operation ran.
4. `rg --files` for AGENTS/models/schema/database/settings/architecture/manifests and relevant tests: only root AGENTS found. `rg -n` for model classes, abstract models, explicit table names, M2M/O2O fields, CREATE TABLE and dynamic-store functions located fixed and dynamic schema sources.
5. Source inspection: all domain model class inventories; detailed relevant regions in ingestion, documents, workflows, identity, evaluations, artifacts, builder, orchestration and tools models. Read settings/test profile, pyproject, ADR-0003 and ADR-0014. Direct references were traced in ingestion services/scheduler/job lifecycle/staged build/vector store, retrieval provider, document access/services, builder API/services, evaluation services, release lifecycle, console operations/views, MCP service and observability signals/retention. Search terms included `DocumentSetGrant`, `IngestionRun`, `IndexedDocument`, `Chunk.objects`, `WorkflowDraft`, `ArtifactDraft`, `ConfluenceSyncRun`, `RestSyncRun`, `EvalRun`, `EvalCaseResult`, `QuestionEvaluationRun`, `eval_suite`, `retention`, `drop_store`, `retire_staged_index`, `select_for_update` and `on_commit`.
6. `Get-Content docs/manual-testing-guide.md` section 0 and canonical Compose definition preceded any runtime query. `docker compose -f deploy/compose/docker-compose.yml ps`: all five app roles running, PostgreSQL/Redis/MinIO healthy. `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/v1/health/live -TimeoutSec 10`: `{"status":"ok"}`. No startup, shutdown, rebuild, seed, migration application or provider call.
7. `Get-Command python,uv` and `Test-Path .venv/Scripts/python.exe`; `.venv/Scripts/python.exe --version`: repository Python available, 3.13.5. Used it throughout rather than the unrelated default Anaconda interpreter.
8. Python stdin with `DJANGO_SETTINGS_MODULE=config.settings.test`, `django.setup()`, `apps.get_models(include_auto_created=True)` and `MigrationLoader(None).project_state()`: both enumerate 89 model/auto-created tables, with empty name-set differences. Generated [inventory.md](inventory.md) from this metadata, listing direct local-field relationships without row contents.
9. Read-only SQL through `docker compose ... exec -T postgres psql -U agenthub -d agenthub -X -v ON_ERROR_STOP=1`: public schema has 99 tables, 90 fixed and 9 dynamic. `pg_total_relation_size` totals fixed=9296 kB, dynamic=9144 kB at the sample. `pg_stat_user_tables.n_live_tup` was misleadingly zero for many populated tables and was explicitly rejected as row-count evidence.
10. Second SQL pass used `BEGIN READ ONLY`, `SET LOCAL statement_timeout='10s'`, generated `SELECT count(*)` for each public table, index-status/type/dimension grouping, and an orphan-store join; ended with `ROLLBACK`. Exact counts establish the review's local examples. Legacy ingestion tables each 0; workflow/artifact drafts 28/13; REST run/cursors 1/2. Source types: generic_rest=1. Indexes: active=5, promotable=1, superseded=3, failed=9. The first three groups have all nine stores; failed rows have none. Orphan stores=0. Only aggregate counts and schema identifiers were read.
11. Python stdin using the test-settings model graph and a local psycopg connection configured `default_transaction_read_only=on`, `statement_timeout=10000`: expected fixed names versus PostgreSQL names have no missing/extra tables. Compared `loader.disk_migrations` against `django_migrations`: no unapplied migration, including working-tree 0016. Installed vector extension: 0.8.4. Local Compose connection coordinates were used without printing credential values; no production system was accessed.
12. `.venv/Scripts/python.exe manage.py makemigrations --check --dry-run --settings=config.settings.test`: exit 0, `No changes detected`. No migration file written.
13. Test names and assertions inspected in builder services, document scenario access, ingestion promotion/vector-store/job-lifecycle/REST/Confluence tests. This confirms intended publication immutability, grant revocation/tenant denial, sync idempotency, retention and transactional delivery boundaries; tests not executed below are inspection evidence only.
14. `.venv/Scripts/python.exe -m pytest apps/builder/tests/test_services.py apps/documents/tests/test_scenario_access.py apps/ingestion/tests/test_rest_pull.py apps/ingestion/tests/test_confluence.py --ds=config.settings.test`: **60 passed, 2 skipped in 21.98s**, exit 0. Skips: `test_rest_pull.py:731` and `test_confluence.py:508`, both require PostgreSQL RLS. Test DB is in-memory SQLite; local application data not changed.
15. Official pgvector documentation searched for mixed-dimension indexing/filtering, then opened [README at v0.8.4](https://github.com/pgvector/pgvector/blob/v0.8.4/README.md), matching installed extension. Used only for external technical constraints, not as evidence that a shared-store design is suitable for this project.

Some initial bounded `rg` requests guessed absent test names (`test_pipeline.py`, ingestion `test_services.py`, `test_artifact_drafts.py`, evaluation `test_lifecycle.py`) and used an unsupported PowerShell path wildcard for `apps/console/scenario*`. They reported path errors; actual filenames were then resolved with `rg --files`, and existing test files were used. These exploratory errors are not passing verification evidence. Large combined read outputs were sometimes truncated; candidate decisions were based on subsequently narrowed reads and exact references.

## Read-only schema queries

The decisive SQL shapes were:

```sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';
SELECT schemaname, count(*) FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema') GROUP BY 1;
SELECT CASE WHEN c.relname LIKE 'chunk_iv_%' THEN 'dynamic_vector' ELSE 'fixed' END,
       count(*), pg_size_pretty(sum(pg_total_relation_size(c.oid)))
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind IN ('r','p') AND n.nspname='public' GROUP BY 1;
SELECT format('SELECT %L AS table_name,count(*) AS exact_rows FROM public.%I;',
              tablename, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename;
-- psql \gexec executes the SELECT statements produced above.
SELECT count(*) AS orphan_stores FROM pg_tables t
LEFT JOIN ingestion_indexversion i ON t.tablename='chunk_iv_'||i.id::text
WHERE t.schemaname='public' AND t.tablename LIKE 'chunk_iv_%' AND i.id IS NULL;
ROLLBACK;
```

Catalog enumeration verifies names/counts, not every live column/index/RLS definition. Aggregate samples were taken while workers ran and are not a frozen snapshot of all runtime rows. No production query plans, latency, recall, lock load or growth-rate benchmark was run.

## Final review and applicable checks

Staff-engineer review: no arbitrary target table count; legacy paths distinguished from unused tables, and mutable/immutable/compiled data not conflated. Each proposed saving is conditional; first-phase arithmetic 3+2+1=6, 80−6=74. Current models/migration endpoints/live table names agree.

Application-security review: no ACL table recommended for unconditional removal; consumer and scenario grants are separate live checks. Typed profile/contract relationships, tenant context, approval provenance, endpoint/secret boundaries and source validation must survive any future consolidation. No authorization change or destructive migration written.

SRE review: outbox/retry/checkpoint boundaries retained; dynamic-store retirement exists but no caller of the retirement service was found. General bulky-state retention does not clean vector stores. No claim that superseded stores are immediately disposable, or that 99 tables cause observed slowness.

Closure checks: Python relative-Markdown-link validation returned `DOCUMENT_LINK_ERRORS []`; generated inventory contains exactly 89 model rows. `git diff --check -- docs/planning/master-plan.md docs/planning/archive/README.md docs/planning/archive/database-architecture-review-2026-09-08` exited 0. Scoped diff and file contents reviewed; new documentation also checked directly because untracked files are not included by ordinary `git diff`. The task directory was moved into the archive with native `Move-Item` only after resolving both absolute paths and confirming they remain inside the workspace and the destination does not exist. Only five review documents and the small index/master-plan insertions belong to this task; pre-existing UI-review additions in those index files remain intact. No commit created.

Not run: full backend/frontend suites, new PostgreSQL non-owner RLS tests, performance/load/recall tests, browser journeys, full scanner/lint/type suite or migration rollback drills. This documentation-only assessment changes no runtime code; those are future implementation gates, not evidence claimed here. No new regression tests were written because there is no behavior change.

## Completion scope

Implemented: assessment and inventory only. Verified: model/migration/live table reconciliation, targeted existing tests and documentation closure. No application simplification has been implemented or verified. Production usage, retention policy and implementation approval remain outside this review.
