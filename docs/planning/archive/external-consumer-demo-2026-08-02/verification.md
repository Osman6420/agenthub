# Verification: external-consumer-demo

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Focused and adjacent tests | `pytest` across console demo, orchestration, agent, workflow and gateway suites | Pass | 81 passed, 10 skipped | Skips require PostgreSQL row locking/RLS; those paths were exercised live. |
| Final focused regression | `pytest apps/console/tests/test_external_consumer_demo.py apps/orchestration/tests/test_rag_steps.py` | Pass | 13 passed | Includes bootstrap fail-closed behavior and provider compatibility. |
| Formatting and lint | `ruff format --check` and `ruff check` on changed Python files | Pass | No findings | No rule suppression added. |
| Type check | `python -m mypy apps` | Pass | 447 source files | Run in the repository's disposable verification container. |
| Django system check | `python manage.py check` | Pass | No issues | Disposable verification container. |
| Migration drift | `python manage.py makemigrations --check --dry-run` | Pass | No changes detected | No schema change. |
| JavaScript syntax | `node --check examples/external-consumer-demo/app.js` | Pass | Exit 0 | Static page has no build dependency. |
| Live public API | Four scenario calls plus denied call | Pass | RAG/brief/smoke completed; agent reached completed; denied call returned 403 | PostgreSQL, Redis, workers and Gemini-backed runtime. |
| Browser | Standalone page at `127.0.0.1:4173` | Pass | Q&A citations, async polling and denial badge visually verified; no console errors | Browser received no bearer tokens. |
| Diff hygiene | `git diff --check` and tracked-secret search | Pass | No whitespace errors; local credential file is ignored | Repeated again at closure. |

## Acceptance criteria mapping
All seven acceptance criteria passed. Three consumers serve four scenarios; the real Turkish
Wikipedia Istanbul extract is indexed and cited; Gemini is resolved through the existing secret
environment seam; the standalone page can run every scenario and the negative authorization case.

## Security requirement mapping
Fixed HTTPS Wikipedia origin, redirect denial, timeout/body bounds, loopback binding, proxy route
allowlist, request/response limits, restrictive browser headers and gitignored credentials are
implemented and tested where applicable. The Gemini key was neither printed nor persisted.

## Authorization tests
Bootstrap tests assert exact scenario bindings and only the operator has a usable password. Live
operations-consumer access to the Wikipedia alias returned `403 SCENARIO_NOT_ALLOWED`.

## Cross-tenant tests
No existing tenant data is reused. All demo rows have direct `external-demo` lineage; the broader
PostgreSQL suite's RLS-only tests are skipped under SQLite, while the live PostgreSQL demo exercised
the scoped gateway, retrieval and run paths.

## Logging and redaction tests
Credentials are absent from tracked files and browser configuration. Existing gateway/provider
redaction remains unchanged; the standalone proxy does not log authorization headers or bodies.

## Audit event tests
Existing gateway and runtime audit paths were exercised live. No audit schema or failure policy was
changed.

## Migration verification
No migration expected; run `makemigrations --check --dry-run`.

## Behavior comparison with base branch
Staff-engineering review: the public API is unchanged and the query now reaches model generation as
explicit untrusted user content. Application-security review: trust boundaries stay fail closed and
the demo proxy is not open-ended. SRE review: startup is explicit, reruns reuse valid credentials,
failures are bounded, and only application Compose roles required recreation.

## Checks not run
The entire repository test suite was not rerun. Production deployment, live LDAP, remote browser
access, and external monitoring validation are outside this local-demo scope.

## Remaining risks
Wikipedia/Gemini availability and content changes affect future bootstraps. Any process running as
the same workstation user can read the local credential file. Deterministic 64-dimensional demo
embeddings are intentionally local-only and are not representative of production retrieval quality.

## Human review required
Review local credential handling before reuse outside a disposable workstation.

## Final status
Verified on 2026-08-02.
