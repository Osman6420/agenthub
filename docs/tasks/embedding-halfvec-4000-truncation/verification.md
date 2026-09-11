# Verification: embedding-halfvec-4000-truncation

## Status

Implemented and backend-verified on 2026-08-03. The task is not marked `Completed` because the
mandatory signed-in browser gate could not proceed past login without user credentials, and no live
governed provider returning more than 4,000 components was available for an external egress smoke.

## Acceptance evidence

| Criterion | Evidence | Result |
| --- | --- | --- |
| Overlong `halfvec(4000)` output retains first 4,000 | `test_max_halfvec_truncates_overlong_vector_before_normalizing` | Passed |
| Normalize after truncation | Prefix `[3, 4, ...]` becomes `[0.6, 0.8, ...]`; discarded `999` does not affect norm | Passed |
| Exact 4,000 accepted | `test_max_halfvec_accepts_exact_dimension` | Passed |
| Short output rejected | `test_max_halfvec_rejects_short_vector` | Passed |
| Other geometries reject overlong output | vector mismatch parameter plus `test_non_max_halfvec_rejects_overlong_vector` | Passed |
| Malformed discarded suffix rejected | `test_max_halfvec_validates_discarded_tail_before_truncating` | Passed |
| No migration drift | `manage.py makemigrations --check --dry-run` | Passed — no changes detected |

## Commands and results

| Check | Result |
| --- | --- |
| Focused `ruff format --check` and `ruff check` on four affected Python files | Passed |
| Repository `ruff check apps` | Passed |
| Repository `ruff format --check apps` | Not clean due to pre-existing unrelated `apps/retrieval/providers.py`; affected files pass |
| Focused SQLite embedding/schema tests in disposable Python 3.13 container | Passed — 30 passed |
| Full SQLite repository suite in disposable Python 3.13 container | Passed — 1,135 passed, 61 PostgreSQL-only skips |
| PostgreSQL/pgvector ingestion suite against healthy canonical Compose services | Passed — 150 passed, 2 expected off-PostgreSQL skips |
| `python manage.py check` | Passed — no issues |
| `python manage.py makemigrations --check --dry-run` | Passed — no changes detected |
| `python -m compileall -q apps config` | Passed |
| `python -m mypy apps` in application image with repository venv-equivalent mypy 2.1.0 / django-stubs 6.0.6 and `PYTHONPATH=/app` | Passed — no issues in 448 source files |
| `git diff --check` on task-owned files | Passed |

The host `.venv` Python launcher failed before Python startup with `A specified logon session does
not exist`; `.venv/pyvenv.cfg` points to an unavailable Microsoft Store Python 3.13 launcher. The
repository-documented disposable-container fallback was used. Initial mypy container attempts also
exposed a packaging-only missing `/app` import path; the final application-image run set
`PYTHONPATH=/app` and passed.

## Runtime and browser evidence

- Canonical Compose state was queried immediately before PostgreSQL testing: PostgreSQL, Redis, and
  MinIO were healthy; web, workers, and beat were running.
- The in-app browser reached the local AgentHub operator login page. No signed-in tab/session was
  available, so role/tenant UI checks were not attempted and no credentials or local accounts were
  changed.
- No live provider with native output above 4,000 was called. Provider-response behavior is proven
  with the injected transport contract tests; pgvector storage behavior is covered by the real
  PostgreSQL ingestion suite.

## Final diff reviews

### Staff engineer

The change is localized to the governed provider adapter. Profile/store dimensions remain capped and
immutable; no database, public API, job, retrieval, or promotion contract changes. ADR-0017 records
the intentional exception to ADR-0003.

### Application security

Only exact `halfvec(4000)` profiles opt in. The adapter validates every component, including the
discarded suffix, before truncation. Short/wrong geometry remains fail-closed. No payload/vector is
logged, and authorization/tenant boundaries are unchanged.

### SRE

Response bytes remain bounded by the existing profile cap. CPU remains linear in the already
received vector length because the entire vector is validated. Rollout uses a new immutable profile
revision and staged build; rollback disables that profile and pointer-flips to the prior index.

## Security, authorization, privacy, and observability

- Authentication, authorization, grants, and tenant isolation: unchanged.
- Data: only the first 4,000 components are retained; suffix is discarded and unrecoverable.
- Privacy/logging/audit: no raw vector, document content, provider body, or suffix is added to logs or
  audit.
- Dependency/secret scan: no dependency or secret changes; no separate secret scanner was run.

## Remaining risks and manual review

- Prefix truncation may reduce semantic retrieval quality; a provider-specific evaluation is
  required before promotion.
- Signed-in browser UI/auth gate remains unverified due to absent session credentials.
- Live >4,000 provider egress and end-to-end staged build remain unverified until an approved profile,
  grant, credential, and endpoint are available.
- The unrelated repository formatter drift in `apps/retrieval/providers.py` remains outside this
  task and was not modified.
