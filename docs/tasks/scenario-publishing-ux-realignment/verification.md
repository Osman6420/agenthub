# Verification — scenario publishing UX realignment

Date: 2026-08-07. Branch: `feat/foundation-sprint-0-1`.

## Static checks

| Command | Result |
| --- | --- |
| `.venv\Scripts\ruff.exe format --check apps` | pass (after formatting the changed modules) |
| `.venv\Scripts\ruff.exe check apps` | `All checks passed!` |
| `.venv\Scripts\mypy.exe apps` | `Success: no issues found in 462 source files` |
| `.venv\Scripts\python.exe manage.py check` | `System check identified no issues (0 silenced).` |
| `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run` | `No changes detected` (no migration added) |
| `.venv\Scripts\python.exe -m compileall apps config` | pass |

## Tests — SQLite (`config.settings.test`)

Full suite: **1209 passed, 61 skipped**, 0 failed (354s).

## Tests — PostgreSQL (`config.settings.local`, `--create-db`, pgvector Compose)

Scope: `apps/releases apps/builder apps/evaluations apps/console apps/workflows`
(657 collected), with `MCP_ENABLED=true` and a non-empty `METRICS_BEARER_TOKEN`.

**656 passed, 1 failed** (1520s). The single failure was
`test_phase_2_5_part_2.py::test_uuid_routes_are_canonical_and_legacy_routes_remain_scoped`
raising `StorageError("STORAGE_PUT_FAILED")` from `apps/documents/storage.py:118` — an
**environment omission in the run, not a regression**: `OBJECT_STORE_ENDPOINT` defaults to
empty (`config/settings/base.py:253`), so `config.settings.local` had no MinIO endpoint and
`upload_document` could not reach object storage. The failure occurs at line 116, before the
test reaches any changed view.

Re-run with the Compose MinIO configured — `OBJECT_STORE_ENDPOINT=http://localhost:9000`,
`OBJECT_STORE_BUCKET=agenthub`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY=minioadmin`:

```
apps\console\tests\test_phase_2_5_part_2.py .....   [100%]
5 passed in 86.85s
```

So the PostgreSQL profile is green: **657/657** across the affected apps once object storage
is reachable. Note for future runs: the PostgreSQL profile needs the MinIO variables above in
addition to `MCP_ENABLED` and `METRICS_BEARER_TOKEN`.

## Frontend (Node v20 / npm 10)

| Command | Result |
| --- | --- |
| `tsc --noEmit` | pass |
| `vitest` | **52 passed** (12 files) |
| `vite build` | pass (`builder.js` 387.64 kB) |

## New and changed tests

- `apps/releases/tests/test_derived_manifest.py` (5) — derivation satisfies every required
  role; the derived manifest compiles; **the released defect is a regression test**
  (type-named roles now raise `workflow_role_unpinned` instead of compiling); missing
  artifacts are reported in author language without leaking the derived role; a foreign
  tenant's artifacts with the *same* logical ids are never resolved.
- `apps/builder/tests/test_publish_and_verify.py` (10) — one call publishes, compiles and
  evaluates; the default suite removes the second-candidate round trip; missing artifacts
  are reported without creating a candidate; viewer denied (403); cross-tenant denied (404);
  never promotes; stale revision rejected (409); derived manifest reports pins; node
  artifact library serves history/copy sources; library denies a viewer.
- `apps/console/tests/test_scenario_setup_steps.py` (3) — steps render in journey order with
  honest state; a Scenario Editor sees authoring actions but the promote control is
  disabled; cross-tenant 404.
- `apps/evaluations/tests/test_evaluations.py` — an `error` run is not reported as a pass
  ratio; passed/failed reported at distinct severities.
- `apps/console/tests/test_scenario_contract_defaults.py` — defaults now cover all three
  scenario-scoped roles; the default eval suite is valid and its input satisfies the default
  input contract.
- Updated to the intended new behaviour (not weakened): `toolbar.test.tsx`,
  `app_deeplink.test.tsx`, `test_phase_2_8_part_1.py`, `test_phase_2_8_part_4.py`.

## Live repair of the reported defect

Against the running Compose stack, for the owner's scenario `ilksenaryo-rhkvva6ffs`:

- `derive_manifest` → `ok=True`, pinning `ret_0c912fc4bda3b3c5a11c6590_profile`,
  `gen_1afcdd2cd8a9777ce5f59afa_prompt`, `gen_1afcdd2cd8a9777ce5f59afa_model` under the
  roles the workflow nodes actually reference (release 33 had pinned the same artifacts as
  `retrieval_profile` / `prompt_template` / `model_profile`).
- Compiled candidate **#34**; `run_eval` → `Eval geçti: 1/1 test sorusu başarılı`,
  `error_code=''`, case `smoke-1` `workflow_completed` → passed.
- Release 33 was left untouched; no promotion or traffic change was made.

## Not run / open

- **Mandatory browser gate** (`manual-testing-guide.md` §10): not yet run. Processes 1, 2 and
  3 must be exercised in a browser with before/after click counts, matched permitted and
  forbidden identities, same-tenant cross-scope and cross-tenant probes, and a console and
  network error review.
- Redis and MinIO remain unexercised by the automated suite (pre-existing).

## Residual risks

- The compile gate is a fail-closed tightening. It rejects only manifests missing a role the
  **compiled workflow requires**; extra pins stay allowed, and no existing active release is
  re-validated. Any GitOps pack or `compile_release` invocation that relied on type-named
  roles for a node-bound workflow will now fail at compile time with `workflow_role_unpinned`
  — this is the intended behaviour and the diagnostic names the role and node.
- The manual manifest path still exists for scenarios with no published workflow. It can no
  longer produce a release that fails at request time, but it remains a raw-identifier
  surface.
- Legacy scenarios holding more than one `WorkflowDraft` fall back to the org-wide Studio
  listing; `release-manifest/derived/` returns `available: false` for them, so their
  candidate preparation still uses the manual panel.
