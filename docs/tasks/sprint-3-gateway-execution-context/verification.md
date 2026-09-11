# Verification: sprint-3-gateway-execution-context

Record every executed command and its result. Do not infer success.

## Environment

- Python (venv): CPython 3.13.14. Django 5.2.16. New dep: djangorestframework 3.17.1
  (see `requirements.lock`).
- Unit gate settings: `config.settings.test` (SQLite `:memory:`, LocMem cache).
- Integration: `config.settings.local` against real PostgreSQL 16 + pgvector 0.8.5.
- Date: 2026-07-10.

## Commands and results

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| Formatter | `ruff format --check .` | PASS | `93 files already formatted` (after applying format) |
| Linter | `ruff check .` | PASS | `All checks passed!` |
| Type-check | `mypy .` | PASS | `Success: no issues found in 98 source files` |
| Migration drift | `makemigrations --check --dry-run` | PASS | `No changes detected` |
| System check | `manage.py check` | PASS | `no issues (0 silenced)` |
| Unit tests (SQLite) | `pytest` | PASS | `59 passed` |
| Integration tests (PostgreSQL) | `DJANGO_SETTINGS_MODULE=config.settings.local pytest --create-db` | PASS | `59 passed` |

## Acceptance-criteria evidence (Sprint 3)

| Criterion | Evidence |
| --- | --- |
| No/invalid token → 401 | `gateway/tests/test_invoke.py::test_missing_token_returns_401`, `..._invalid_token_returns_401`; live: 401 `AUTHENTICATION_REQUIRED`. |
| Unauthorized alias → 403 | `..._unbound_alias_returns_403` (`SCENARIO_NOT_ALLOWED`); live confirmed. |
| Missing capability → 403 | `..._missing_capability_returns_403` (`CAPABILITY_DENIED`). |
| No access via raw project/release id | `..._raw_ids_do_not_grant_access` — body with only `project_id`/`release_id` → 400 (routing is by bound alias). |
| Idempotency conflict → 409 | `..._idempotency_replay_and_conflict`; live: replay returns same `request_id`, differing body → 409 `IDEMPOTENCY_CONFLICT`. |
| ExecutionContext signed + expiring | `gateway/tests/test_execution_context.py` (roundtrip, tamper → bad signature, expiry rejected). |
| Input validated against contract | `..._input_contract_violation_returns_400`; live: empty input → 400 `INPUT_CONTRACT_VIOLATION`. |
| Token stored hashed, fail-closed | `identity/tests/test_tokens.py` (hashed at rest; unknown/revoked/disabled → None). |
| Stable error-code contract | `gateway/tests/test_contract.py` snapshot of `ERROR_CODES`. |
| Per-consumer rate limit | `gateway/tests/test_throttle.py` (blocks after limit; ignores unauthenticated). |

## Manual end-to-end (dev PostgreSQL, live HTTP)

Token minted with `create_consumer_token --organization mcm --subject ug-backend`.
Against the running server (`POST /v1/invoke`, `/v1/query`):

- No token → `401 AUTHENTICATION_REQUIRED`.
- Valid token + `{"input":{"query":"…"}}` → `200` `{"status":"accepted","release_id":1,
  "output":null}` (ExecutionContext issued; runtime pending).
- `{"input":{}}` → `400 INPUT_CONTRACT_VIOLATION`.
- Unbound alias → `403 SCENARIO_NOT_ALLOWED`.
- `Idempotency-Key` replay (same body) → identical `request_id`; different body → `409
  IDEMPOTENCY_CONFLICT`.
- `/v1/query` facade → `200 accepted`.
- Every response carries an `X-Request-ID` header.

## Notes / skipped checks

- No model output is generated (runtime facade returns `accepted`); the RAG runtime,
  output-contract/policy enforcement, and streaming arrive in Sprint 4/onward.
- Bearer token is the only credential type this sprint; OIDC/JWT/mTLS are pluggable
  later without changing the flow.
- OpenAPI document generation (drf-spectacular) is deferred; the error-code contract
  is snapshot-tested instead. Rate-limit accuracy depends on the shared cache
  (fail-open on limiting only; auth/authz never fail open).
