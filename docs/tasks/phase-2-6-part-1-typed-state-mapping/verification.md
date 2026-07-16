# Verification: phase-2-6-part-1-typed-state-mapping

## Status

Implemented and verified on branch `phase-2-6/p2-6-1-state-mapping` (from baseline
`feat/foundation-sprint-0-1` @ `88fc203`). Not merged to any integration branch.

## Dependencies / decisions closed

- P2.6.0 contract foundation, ADR-0008 and ADR-0010 (accepted) are the source contracts.
- Open questions closed in [`decisions.md`](decisions.md): transform = pinned-profile-only (D1);
  fixed pointer/mapping limits (D2); optional additive mappings with node-local isolation when present
  (D3); compiled contract bumped to `agenthub/compiled-workflow/v2` with no DB migration (D4);
  deny-by-default protected-namespace allowlist (D5); runtime type/missing checks before side effects
  (D6).

## Changes under test

- `apps/workflows/state_mapping.py` (new): shared restricted JSON Pointer parser, protected-namespace
  policy, bounded mapping compiler, node-local envelope build + copy-on-success output mapping.
- `apps/workflows/compiler.py`: `transform` node, optional `input_mapping`/`output_mapping` on eligible
  nodes, tool input/output-sink rules, compiled `api_version`/`compiler_version` v2 bump.
- `apps/workflows/runtime.py`: node-local input envelope, atomic output mapping, governed transform
  executor, stale-compiled-contract guard.
- `apps/workflows/services.py`, `models.py`: v2 compiler version wiring (no schema change).
- `apps/releases/compiler.py`: fail-closed transform-profile pin check.
- `apps/builder/node_schema.py`: transform node + mapping metadata parity.
- Docs: workflow LLM guide, detailed authoring guide, task decisions.

## Commands and results

Runner: repo-root project venv `../agenthub/.venv` (Python 3.13.14) executed with the worktree as
CWD (module resolution confirmed to load the worktree's `apps/*`, not the editable install).

SQLite profile — `DJANGO_SETTINGS_MODULE=config.settings.test`:

- `ruff format --check apps` → 365 files already formatted (pass).
- `ruff check apps` → All checks passed.
- `mypy apps config` → Success: no issues found in 375 source files.
- `python manage.py check` → System check identified no issues (0 silenced).
- `python manage.py makemigrations --check --dry-run` → No changes detected (no migration required).
- Focused: `test_state_mapping.py` 47 passed; `test_compiler.py` 17 passed; `test_transform_node.py`
  4 passed; `test_tool_node.py` 4 passed.
- Affected apps `apps/workflows apps/builder apps/releases apps/artifacts` → 202 passed.
- Full suite `pytest` → **774 passed, 29 skipped** (all skips are PostgreSQL-only: pgvector / advisory
  locks / RLS).

PostgreSQL profile — `DJANGO_SETTINGS_MODULE=config.settings.local` against Compose
pgvector/Redis/MinIO, `MCP_ENABLED=true`, `METRICS_BEARER_TOKEN` set, `--create-db`:

- Broad `apps/workflows apps/releases apps/builder apps/tenancy` → **183 passed, 3 skipped, 5 errors**.
  The 5 errors are shared-`test_agenthub` teardown/flush collisions ("database is being accessed by
  other users") on the pre-existing `transaction=True` gateway test and four pre-existing tenancy RLS
  tests — an environmental shared-DB session issue documented in the manual testing guide, not an
  assertion failure and not touched by this change.
- Focused isolated re-run (after terminating lingering sessions and dropping the stale test DB):
  `test_state_mapping test_compiler test_transform_node test_tool_node` + `releases/test_compiler` +
  `builder/test_api` → **122 passed** (one harmless teardown warning). This exercises the transform
  node, typed mappings, release pin check and runtime on real PostgreSQL.

## Acceptance-criteria mapping

1. Pointer grammar — `test_state_mapping::test_parse_pointer_*` (canonical accept + every forbidden
   form + length/depth). Diagnostic `WORKFLOW_PATH_INVALID`.
2. Shared compiler/runtime policy — one module `state_mapping.py` imported by compiler, release
   compiler and runtime; protected write denial `test_output_mapping_denies_protected_and_unknown_roots`.
3. Bounded exact entries / conflicts — `test_compile_mappings_rejects_malformed_lists`,
   `test_output_mapping_rejects_conflicting_destinations`, compiler `test_compile_rejects_unsafe_mappings`.
4. Author/compile + runtime schema/type checks — compiler mapping validation + runtime
   `WORKFLOW_MAPPING_MISSING`/`WORKFLOW_MAPPING_TYPE_MISMATCH` (`test_apply_output_mapping_*`).
5. Atomic failure, no partial mutation — `test_apply_output_mapping_is_copy_on_success_and_atomic`.
6. Tool/retrieve/generate/custom mapped input+output preserving auth — `test_tool_node_typed_input_and_output_mappings`
   (tool approval/proxy path unchanged; output routed to `/evidence` + `/output`).
7. Transform pinned/allowlisted only — `test_transform_node_runs_pinned_profile_and_maps_output`,
   `test_release_fails_closed_when_transform_profile_not_pinned`,
   `test_transform_node_unresolved_profile_fails_closed`.
8. Deterministic/redelivery + terminal guard — existing `test_runtime` idempotency/redelivery pass;
   `test_runtime_rejects_stale_compiled_contract_version` proves the v2 contract guard.
9. Author/diagnostics/publish/compile/runtime parity — builder `diagnose` reuses the compiler; node
   schema parity `test_node_schema_includes_transform_and_mapping_metadata`.
10. New grammar compiles; stale compiled grammar rejected — v2 bump + runtime guard; source grammar is
    backward compatible (mappings optional), so existing fixtures still compile.
11. Redaction/telemetry safety — mappings move already-redacted state; diagnostics are stable
    content-free codes; no new logs/metric labels added.
12. SQLite + PostgreSQL + migration-drift evidence — recorded above.

## Checks not run / residual risk

- No live model/embedding/tool egress (default deterministic providers; no-egress tool adapter). No
  Redis/Celery real-broker soak beyond the existing suite.
- The 5 PostgreSQL teardown-collision errors were not re-run to green in the broad combined run; the
  affected tests were proven green in isolation. They are pre-existing and unrelated to this change.
- Cross-node schema inference is intentionally deferred to runtime (D6); a mapping whose source type
  is only known at runtime fails closed before any side effect rather than at compile time.
- Parallel/join/wait/human-task/child grammar is out of scope (later parts); the P2.6.0 target
  fixtures using those primitives remain inert `target_not_importable` wrappers.
- `AGENTS.md` "Repository-specific verified state" is intentionally not edited on this feature branch;
  the integration owner updates it when P2.6.1 merges into the Phase 2.6 integration branch.
