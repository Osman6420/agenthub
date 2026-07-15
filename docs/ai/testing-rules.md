# Testing Rules

## Test strategy

Use the lowest-cost layer that proves the behavior, plus real-boundary coverage where risk demands it:

- Unit tests isolate deterministic domain rules.
- Integration tests verify database, queue, cache, provider adapter, authorization, and audit boundaries.
- Contract tests protect public APIs/events/provider assumptions and backward compatibility.
- End-to-end tests cover a few critical user and operational flows.
- Migration tests prove forward transition, compatibility during rollout, data invariants, and rollback/forward-fix strategy.
- Security tests cover abuse cases, validation, injection/SSRF/path/upload controls, privilege escalation, and isolation.
- Performance/load tests are required for latency/throughput objectives, unbounded work risks, concurrency, queues, or material query changes.

Tests must be deterministic, isolated, order-independent, and safe for parallel execution. Use synthetic/anonymized data and no production secrets/data. Mock unstable or expensive edges, not the authorization policy, schema, persistence constraints, or critical integration contract being proved.

## Required cases

For applicable behavior test happy path, invalid/unexpected input, boundary values, authentication failure, authorization denial, cross-user/cross-tenant access, dependency failure/timeout, retries and idempotency, concurrency, audit event content/delivery behavior, sensitive-data redaction, and backward compatibility. Migration changes require representative data and constraint validation.

Quarantine a flaky test only with ownership, evidence, risk, and a removal deadline; never silently rerun indefinitely. Never delete a failing test, weaken its assertion, or bypass a control to make a check green.

## Repository commands

The repository-verified host commands are:

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\ruff.exe format --check apps
.venv\Scripts\ruff.exe check apps
.venv\Scripts\mypy.exe apps
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.venv\Scripts\python.exe -m compileall apps config
```

Run tests without pytest `-q` so collection, progress, skips and failure context remain visible. Do
not impose a pytest timeout; allow the suite to finish, using a background process plus log polling
when the calling tool cannot remain attached indefinitely. A command-runner safety ceiling is not a
substitute for a pytest timeout and must be long enough not to terminate a healthy suite.

The SQLite test settings do not prove PostgreSQL RLS, pgvector, advisory-lock or retrieval behavior.
Applicable work must also run the PostgreSQL profile documented in
[`manual-testing-guide.md` section 0.1](../manual-testing-guide.md#01-windows-pythontest-troubleshooting).
That section is also the canonical recovery procedure for Microsoft Store venv launcher failures,
Python ABI mismatches, unrelated pytest plugin autoload failures and the known Compose image
build-order defect. Record the exact profile, pass/skip counts and environmental fallback in the
task verification file.
