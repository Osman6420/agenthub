# Verification — product-led RAG architecture reassessment

Date: 2026-09-08. Checkout: `feat/foundation-sprint-0-1`, HEAD `2c3e959` plus existing uncommitted work. Review documents are the only changes owned by this unit. No application/authorization/schema/runtime lifecycle changes.

## Scope confirmation

The owner explicitly permits reconsidering architecture and behavior because the application is not live. They confirmed (1) mutually isolated teams/data areas and (2) long-running agents, human approval, parallel workflows and compensation in initial scope. The plan was updated before the target design was written. This is an assessment, not authorization to reset/discard local data, add a dependency or implement a new policy.

The earlier database review is contextual evidence for the current-model-preserving question only. Its 80→74 recommendation and its prior test result are not the scope or verification of this new target. No archived record was rewritten to imply otherwise.

## Source and structural inspection

Executed `git status --short`, `git branch --show-current`, `git rev-parse --short HEAD`; inspected existing unrelated changes. Read root instructions already in context, task documentation/template conventions, definition of done, prior assessment, master plan, architecture overview and README. README has historical statements that conflict with current source; code and current service paths were used as authority instead.

Code-intelligence tool metadata search again found no callable Codebase Memory/Serena tools. No graph was relied on. Used `rg --files`, `rg -n`, direct bounded source reads, AST and Django model/migration metadata.

Evidence map:

| Finding / judgment input | Inspected source and exact seams |
|---|---|
| Independent node-owned prompt/model/retrieval drafts and artifacts | `apps/builder/services.py`: `save_generate_node_binding`, `_upsert_node_artifact_draft`, `_publish_node_artifact_if_changed`, `_publish_generate_bindings`, `_publish_retrieve_bindings`, `publish_draft`, `publish_and_verify` |
| Manifest/pin/compiled workflow/release separation | `apps/releases/compiler.py`: `compile_release`, `workflow_manifest_requirements`, `_assert_workflow_roles_pinned`; `apps/releases/authoring.py`; `apps/workflows/models.py` and `composition.py` |
| Publication and activation are distinct | `apps/releases/lifecycle.py`: `_assert_release_gate`, `promote`; `apps/catalog/lifecycle.py`: `_transition`; ADR-0016 |
| Data-version publishing dependency | `apps/documents/services.py`: `pinned_document_set_version_ids`; `apps/ingestion/staged_build.py`: `promote_staged_index`, `_serve_index`, `active_releases_pinning_document_set_version`, `_compatible_parent`; `apps/retrieval/providers.py`: `_retrieve_acl`; `apps/orchestration/resolver.py` |
| Exact-object operator policy beyond team affiliation | `apps/identity/authorization.py`, `models.py`, `roles.py`, `capabilities.py`; `apps/documents/access_services.py` |
| Real advanced workflow requirements | `apps/workflows/models.py`, `transitions.py`, `run_waits.py`, `run_recovery.py`, `run_parallel.py`, `run_children.py`, `unified_executor.py`; ADR-0008 |
| Non-trivial reuse coupling | `apps/workflows/services.py`, `runtime.py`, `run_children.py`, `unified_executor.py`, `apps/orchestration/rag_steps.py`, `apps/tools/proxy.py` directly reference release/artifact resolution |
| MCP directions and missing dedicated ingestion adapter | `apps/mcp/service.py`, `views.py`, `apps/tools/mcp_adapter.py`, `catalog_sync.py`, `apps/ingestion/models.py:ConnectorType`, `connectors.py`; exact searches for `resources/`, `tools/list`, `tools/call`, protocol constants |
| Tool approval/side effects remain core | `apps/tools/approvals.py`, `adapters.py`, approval tests: request hash, real initiator caveat, expiry, input-swap denial, uncertain outcome and idempotency |
| Complexity not equivalent to table count | `apps/artifacts/types.py` has 15 ArtifactType values in one model; AST counted 24 operator Capability assignments in `identity/authorization.py` |

Bounded source inventories also counted production Python files/physical lines excluding tests/migrations/`__init__.py`: artifacts 12/1304; releases 15/1980; builder 8/4096; identity 11/1778; workflows 22/8004; ingestion 53/10245; tools 16/2740; documents 11/3075. These are navigation context only, not a productivity, code quality or rewrite-cost metric.

Python stdin with `DJANGO_SETTINGS_MODULE=config.settings.test`, `django.setup()`, `apps.get_app_configs()` and `MigrationLoader(None)` verified:

```text
CURRENT_MODELS 80 MAPPED_MODELS 80
MISSING [] EXTRA []
CURRENT_MIGRATION_TABLE_NAMES_MATCH 89
```

The generated proposed group inventory has exactly 35 unique named target models. Every one of the current 80 concrete application models appears once in the mapping. Mapping completeness does not prove feature or data migration equivalence. Logical table count excludes Django and any additional physical vector relations.

Some initial exact-path guesses were absent (`apps/console/scenario_services.py`, `apps/identity/operator_capabilities.py`, workflow test names `test_transitions.py`, `test_parallel.py`, `test_composition.py`, `human_tasks.py`, `compensation.py`, and generic root conftest paths). `rg` reported these; actual paths were then resolved using `rg --files`. Large combined reads sometimes truncated; narrowed reads were used for decisive claims. No absent-path result was treated as passing evidence.

## Tests executed this turn

Initial command:

```powershell
.venv/Scripts/python.exe -m pytest apps/workflows/tests/test_unified_run.py apps/workflows/tests/test_unified_parallel.py apps/workflows/tests/test_unified_children.py apps/tools/tests/test_approvals.py --ds=config.settings.test
```

Result: **2 failed, 75 passed, 11 skipped in 25.69s**, exit 1. Failures:

- `test_bounded_executor_runs_retrieve_and_generate_through_the_governed_seams` (`test_unified_run.py:2145`).
- `test_bounded_executor_routes_rag_nodes_through_typed_mappings` (`test_unified_run.py:2180`).

Both expected completed but the Run was failed. A narrow Python/pytest hook reran only those two, printing status/error/reason codes from the test database without content or credentials: both `WORKFLOW_GENERATION_FAILED`, 2 failed in 22.28s. Effective test settings reported `MODEL_PROVIDER_EXPLICIT True`, `EMBEDDING_PROVIDER_EXPLICIT False`. Source confirms `test.py` imports base settings and does not reset `RUNTIME_MODEL_PROVIDER`; base reads it from the environment/optional local dotenv. The RAG fixtures do not supply the real-provider model profile expected by the provider path. This supports environment dependence; no application bug fix was attempted.

Controlled isolation rerun used this Python stdin process setup before the unchanged test list:

```python
import os, pytest
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'
os.environ['RUNTIME_MODEL_PROVIDER'] = ''
import django
django.setup()
from django.conf import settings
assert settings.RUNTIME_MODEL_PROVIDER == ''
raise SystemExit(pytest.main([
    'apps/workflows/tests/test_unified_run.py',
    'apps/workflows/tests/test_unified_parallel.py',
    'apps/workflows/tests/test_unified_children.py',
    'apps/tools/tests/test_approvals.py',
    '--ds=config.settings.test', '--tb=short',
]))
```

Result: **77 passed, 11 skipped in 26.01s**, exit 0. Only the spawned test process used the repository's existing default StubModelProvider. No test, assertion, provider implementation, `.env`, settings file or live application environment was modified. The initial failing result remains recorded. This is deterministic/offline core evidence, not real-provider or production readiness evidence.

Skipped tests require PostgreSQL row locks/RLS/role grants: unified_run decorators at lines 702, 1222, 1362, 1405, 1445, 1520, 1625, 1667, 1715, 1837; unified_parallel at line 270. Tests that ran include wait/recovery paths applicable to SQLite, parallel convergence/idempotency, child execution and tool approval/input binding/uncertain outcome. No claim that SQLite verified PostgreSQL concurrency or isolation enforcement.

## Primary external references

- [Temporal workflow definition](https://docs.temporal.io/workflow-definition): replay determinism and versioning constraints for long-lived workflows; used as a general design comparison, not adoption approval.
- [Temporal execution](https://docs.temporal.io/workflow-execution): persistence/recovery approach; not a cost or deployment benchmark.
- [MCP resources 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/resources), [tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) and [authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization): distinguish resource ingestion, tool calls and serving directions. Current application adapter explicitly selects 2025-06-18, so newer documentation is not evidence of application compatibility.
- [MCP authorization 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization): token audience and passthrough boundaries for the application's referenced protocol version.
- [pgvector README v0.8.4](https://github.com/pgvector/pgvector/blob/v0.8.4/README.md): mixed-dimension storage and partial/expression index constraints, matching the earlier local extension inventory.

Initial broad searches also returned third-party results; these were not used as technical authority. Dify publishing/index pages were explored but the documentation index child returned a non-retryable safe-open error, so no Dify feature/price/adoption claim is made. A newer MCP security-best-practices URL also returned a safe-open error; the opened version-specific authorization pages support the cited security claims. No access workaround was attempted.

## Staff / application-security / SRE review

Staff: owner-confirmed advanced runtime preserved; proposed simplification removes independent product concepts rather than merely combining tables. 35-model list accounts for M2M links and openly identifies removed optional behaviors. New design and old ADR facts are separated. Existing engine coupling and rewrite uncertainty are explicit.

Application security: workspace isolation remains server-owned; role simplification is a future authorization contract change, not an implemented relaxation. Published allowlists and current policy intersect. Source ACL scope, revoked access, secret rotation, tool-prompt injection, on-behalf-of identity and initiator provenance are explicit. Target does not store arbitrary authority or large mutable histories in JSON.

SRE: technical snapshots, atomic generation flip, old-job engine compatibility, outbox, fencing, unknown side effects, retained approval/compensation and retention dependencies remain. No exactly-once external effect, deterministic LLM reproduction, instant rewrite or performance gain is promised. No runtime state from the prior handoff was relied on; no live application/database diagnosis or lifecycle action ran this turn.

## Closure and limitations

Documentation-only output: plan, threat model, assessment, target model and verification, with archive/master-plan index links. No new architecture ADR adopted. Relative links, target/model counts, whitespace, conflict markers and scoped diff checked at closure; untracked documents checked directly because ordinary git diff excludes them. Existing previous-review/UI-review insertions in shared planning files retained. No commit, reset, migration or dependency installation.

Final structural check exited 0 with `PASS: 5 review docs; local links; 35 unique target models; complete 80-model map; whitespace; markers; plan closure; master/archive links`. Scoped `git diff --check` also exited 0. Both archive move paths were resolved and verified inside the workspace before native `Move-Item`; the destination was required not to exist.

Not run: PostgreSQL non-owner/locking suite, full backend/frontend suites, new architecture prototype, MCP server integration, real provider calls as a verification exercise, production workloads/recall benchmarks, browser journeys, migration/backfill/rollback drills or full lint/type/security scanners. Runtime-changing gates are N/A to writing this assessment; the same checks become required for an approved implementation. No tests for new behavior were added because no new behavior was implemented.

Assessment verification is complete independently of whether the owner adopts it. Open product decisions include within-team/source ACLs, MCP OAuth requirements, retention/longest-run window, local data to preserve and workload scale. All target behavior remains unimplemented and unverified until a separate prototype/implementation task.
