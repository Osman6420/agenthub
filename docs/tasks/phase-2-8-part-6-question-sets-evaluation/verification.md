# Verification: Phase 2.8 Part 6 — Question sets and evaluation

> **Status: Implemented and automated/offline verified on 2026-07-29.**

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| Focused Part 6 and regressions | `python -m pytest apps/evaluations/tests apps/console/tests/test_phase_2_8_part_6.py apps/retrieval/tests/test_pgvector_provider.py apps/retrieval/tests/test_acl_retrieval.py apps/tenancy/tests/test_rls_readiness.py::test_provisioning_sql_names_every_protected_table --create-db` | Pass | 35 passed |
| Full repository, clean PostgreSQL | `python -m pytest --create-db` | Conditional pass | 1,045 passed, 5 skipped; 8 MCP/metrics feature-route failures under `config.settings.local` |
| Feature-route baseline | `DJANGO_SETTINGS_MODULE=config.settings.test python -m pytest apps/mcp/tests/test_mcp.py apps/observability/tests/test_telemetry.py --create-db` | Pass | 14 passed; closes all 8 local-feature-flag failures |
| Django system checks | `python manage.py check` | Pass | No issues |
| Migration drift | `python manage.py makemigrations --check --dry-run` | Pass | No changes detected |
| Formatting/lint | `python -m ruff format --check apps` and `python -m ruff check apps` | Pass | 420 files formatted; all checks passed |
| Static typing | `python -m mypy apps` | Pass | 420 source files |
| PostgreSQL migration | `docker compose ... run --rm migrate` | Pass | `evaluations.0003_question_sets_evaluation` applied |
| Local runtime | restart `web worker-eval`; `GET /v1/health/live` | Pass | HTTP 200 `{"status": "ok"}` |
| Browser journey | In-app browser to local question-set route | Blocked | Browser policy explicitly denied `127.0.0.1:8000`; no workaround attempted |

## Verified behavior

- Draft validation rejects duplicate case IDs, unsupported/unbounded assertions and oversized data.
- Published question-set versions/cases are immutable; optimistic draft revisions reject stale writes.
- Retrieval scoring verifies hit@k, recall@k, MRR, checksums and explicit unscored denominators.
- Answer evaluation verifies exact-release execution, deterministic exact/contains/citation/schema
  assertions, pinned judge success and malformed-judge unscored behavior.
- Result UI verifies failed/unscored/error filtering and separately renders only the judge verdict,
  safe reason code and immutable model/prompt checksums while confidential content stays redacted.
- Run idempotency, cancellation, bounded evidence retention/legal hold and one-off non-persistence pass.
- Cross-tenant console access is non-disclosing; auditors cannot mutate or read confidential content.
- PostgreSQL tests verify FORCE RLS and non-owner isolation for every evaluation table.
- Production app-role provisioning names all new protected evaluation tables with least-privilege
  immutable versus mutable grants.
- Metric labels and audit payloads contain only low-cardinality status/kind and safe identifiers,
  never questions, answers or chunks.

## Review findings

Staff review found the change additive and backward-compatible with existing `eval_suite` callers.
AppSec review confirmed server-side object authorization before the internal operator-test retrieval
path, direct tenant lineage/FORCE RLS, content-free telemetry and no chain-of-thought persistence.
SRE review confirmed bounded cases/evidence, idempotent admission, retry limits, cancellation,
retention and low-cardinality metrics. No unresolved critical or high finding remains.

## Remaining owner acceptance

The authenticated visual browser journey and optional live LLM judge/provider are not claimed as
live verified. The judge remains disabled by default until an approved immutable model profile,
prompt contract and privacy/cost review exist. Manual guide rows 8.13–8.17 record the remaining
browser checks.

## Final status

**Implemented and automated/offline verified.** Production/live-provider activation remains a
separate owner acceptance gate.
