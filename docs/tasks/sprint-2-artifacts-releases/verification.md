# Verification: sprint-2-artifacts-releases

Record every executed command and its result. Do not infer success.

## Environment

- Python (venv): CPython 3.13.14. Django 5.2.16. New deps: jsonschema 4.26.0,
  PyYAML 6.0.3 (see `requirements.lock`).
- Unit gate settings: `config.settings.test` (SQLite `:memory:`).
- Integration: `config.settings.local` against real PostgreSQL 16 + pgvector 0.8.5.
- Date: 2026-07-10.

## Commands and results

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| Formatter | `ruff format --check .` | PASS | `75 files already formatted` |
| Linter | `ruff check .` | PASS | `All checks passed!` |
| Type-check | `mypy .` | PASS | `Success: no issues found in 75 source files` |
| Migration drift | `makemigrations --check --dry-run` | PASS | `No changes detected` |
| System check | `manage.py check` | PASS | `no issues (0 silenced)` |
| Unit tests (SQLite) | `pytest` | PASS | `37 passed` |
| Integration tests (PostgreSQL) | `DJANGO_SETTINGS_MODULE=config.settings.local pytest --create-db` | PASS | `37 passed` |

## Acceptance-criteria evidence (Sprint 2)

| Criterion | Evidence |
| --- | --- |
| Compile fails on missing reference | `releases/tests/test_compiler.py::test_compile_fails_on_missing_reference` (CompileError; no candidate created). |
| Compile fails on schema mismatch | `artifacts/tests/test_artifacts.py::test_invalid_json_schema_contract_rejected` (invalid JSON Schema rejected at creation); compiler re-validates pinned bodies. |
| Compile fails on inline secret | `artifacts/.../test_inline_secret_rejected` (creation) and `releases/.../test_compile_fails_on_inline_secret_in_pinned_body` (compiler defense-in-depth). |
| Artifact version immutable | `artifacts/tests/test_artifacts.py::test_artifact_is_immutable` (save/delete raise). |
| Single active release (DB-enforced) | `releases/tests/test_compiler.py::test_single_active_release_constraint` (IntegrityError on second active) — verified on SQLite and PostgreSQL partial index. |
| Promote swaps active atomically | `..._promote_supersedes_previous_active` (exactly one active remains). |
| Deterministic manifest checksum | `..._compile_happy_path_is_deterministic` (same inputs → same SHA-256). |

## Manual end-to-end (dev PostgreSQL, real CLI)

- `manage.py migrate` applied `artifacts/releases` 0001 — OK.
- `import_gitops --path gitops/mcm/artifacts --organization mcm` → imported 4
  artifacts (input/output contracts, policy, model profile). The model profile's
  `api_key: secret:llm-default-token` reference was accepted; an inline literal
  would have failed.
- `validate_artifacts --organization mcm` → `checked 4 artifact(s), 0 failure(s)`.
- `compile_release --scenario mcm/musteri_deneyimi/musteri_bilgi_sorgula
  --spec gitops/mcm/releases/customer-information.yaml --promote` →
  `compiled candidate release id=1 sha256=7ca0ba08...`, then `promoted ... to active`.
- Console (admin login) dashboard shows 4 Artifacts / 1 Release; Artifacts screen
  lists all four; Releases screen shows the `active` release for
  `musteri_bilgi_sorgula` (runtime `agenthub-runtime:3.0.0`).

## Notes / skipped checks

- Inline-secret detection is a conservative key/reference heuristic (see
  `artifacts/secrets.py`); complements, does not replace, CI secret scanning (planned).
- Full promotion/canary/rollback lifecycle and evaluation gates are Sprint 6; the
  `promote_release` here is the minimal atomic swap needed to demonstrate the
  single-active invariant.
- Console screens remain read-only; artifact/release authoring via the UI is future
  work. Operator actions currently go through management commands (audited).
