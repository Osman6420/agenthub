# Threat Model: sprint-0-foundation

## Assets

- Django signing key and infrastructure credentials (DB, Redis, object store).
- The operational health surface (`/v1/health/*`).
- The CI pipeline and dependency supply chain.

## Trust boundaries

- Environment → application configuration (env vars are the only secret source).
- Public network → health endpoints (unauthenticated).
- Application → PostgreSQL, Redis, MinIO (dev only, private network in target).

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Health endpoint leaks stack trace / connection string / secret | Readiness returns coarse `ok`/`error` per dependency; exceptions are caught and logged internally, never returned to the client. Reviewed in tests. |
| Secrets committed to source control | Secrets read only from environment; `.env` git-ignored; `.env.example` holds no real values; `production.py` fails closed if required secrets are missing. |
| Debug mode / verbose errors in production | `DEBUG` defaults False; `production.py` enforces secure cookies, HSTS, SSL redirect, and required `ALLOWED_HOSTS`. |
| Dependency / supply-chain tampering | Dependencies declared explicitly; `pip freeze` evidence recorded; dependency and container scanning listed for CI hardening (future sprint). |
| Health endpoints used for resource exhaustion | Liveness is a constant-time response; readiness uses short connect timeouts on dependency checks. Rate limiting is added with the gateway (Sprint 3). |
| Cross-tenant / authorization abuse | Out of scope in Sprint 0 — no tenant data or authenticated actions exist yet; enforced from Sprint 1 onward. |

## Residual risk

- Readiness endpoint is unauthenticated and reveals coarse up/down of dependencies.
  Acceptable for an operational probe; network policy restricts exposure in the
  target deployment (Sprint 7+).
- Test settings use SQLite, so Postgres-specific failure modes are not exercised
  until integration tests arrive in Sprint 5.
