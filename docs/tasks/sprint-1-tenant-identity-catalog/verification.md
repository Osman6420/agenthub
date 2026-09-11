# Verification: sprint-1-tenant-identity-catalog

Record every executed command and its result. Do not infer success.

## Environment

- Python (venv): CPython 3.13.14. Django 5.2.16.
- Unit gate settings: `config.settings.test` (SQLite `:memory:`, isolated).
- Integration settings: `config.settings.local` against the real PostgreSQL 16 +
  pgvector 0.8.5 container (`agenthub-postgres-1`, localhost:5432).
- LDAP: disabled in dev/CI/test (python-ldap not installed on Windows); the model
  backend authenticates local accounts. LDAP backend config exercised only by
  `manage.py check` import, not a live bind.
- Date: 2026-07-10.

## Commands and results

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| Formatter | `ruff format --check .` | PASS | `50 files already formatted` |
| Linter | `ruff check .` | PASS | `All checks passed!` |
| Type-check | `mypy .` | PASS | `Success: no issues found in 50 source files` |
| Migration drift | `manage.py makemigrations --check --dry-run` | PASS | `No changes detected` |
| System check | `manage.py check` | PASS | `no issues (0 silenced)` |
| Unit tests (SQLite) | `pytest` | PASS | `23 passed` |
| Integration tests (PostgreSQL) | `DJANGO_SETTINGS_MODULE=config.settings.local pytest --create-db` | PASS | `23 passed` — migrations applied to real Postgres |

## Acceptance-criteria evidence (Sprint 1)

| Criterion | Evidence |
| --- | --- |
| Cross-tenant read denied | `tenancy/tests/test_isolation.py` (member sees only their org; non-member/anonymous see nothing) and `console/tests/test_console.py::test_projects_list_is_tenant_scoped` (org-B project absent from org-A member's screen). |
| Disabled consumer not resolvable | `identity/tests/test_binding.py::test_resolve_denies_disabled_consumer` and `..._disabled_binding`. |
| Alias unique within organization | `catalog/tests/test_constraints.py::test_alias_unique_within_organization` (IntegrityError) + `..._different_organizations` (allowed). |
| Console auth + scope; admin off in prod | `console/tests/test_console.py`: dashboard requires login; local sign-in works; platform admin sees all; `test_django_admin_route_follows_setting` asserts 404 when disabled (test settings) / routed when the dev flag is on. |
| Capability allowlist | `identity/tests/test_binding.py::test_binding_rejects_unknown_capability`. |
| Cross-org binding rejected | `identity/tests/test_binding.py::test_binding_rejects_cross_organization`. |
| Audit append-only | `audit/tests/test_audit.py` (append; save/delete raise). |

## Manual end-to-end (dev Postgres, seeded data)

- `manage.py migrate` applied `tenancy/identity/catalog/audit` 0001 to real Postgres — OK.
- Seeded org `mcm`, project `musteri_deneyimi`, scenario `musteri_bilgi_sorgula`
  (rag/active), alias `customer-information`, consumer `ug-backend` + binding.
- `GET /` → 302 `/console/`; `GET /console/` anonymous → 302 login; login
  `admin` → 302 `/console/`; dashboard shows 1 organization / 1 project /
  1 scenario / 1 consumer; scenarios screen lists `mcm / musteri_bilgi_sorgula`.

## Notes / skipped checks

- LDAP is configured but not installed or bound in this environment (Windows/
  python-ldap). The disabled fallback path is verified; a real LDAPS bind and
  group→role mapping must be validated in a Linux environment before enabling LDAP
  in production.
- Console provides read-only, tenant-scoped screens in Sprint 1; create/edit flows
  and capability enforcement on the request path arrive with the gateway (Sprint 3).
- Secret and dependency/container scanning remain planned CI hardening.
