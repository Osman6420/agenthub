# Verification: Phase 2.5 Part 9 integrated hardening

## Status

Completed, verified and owner-accepted on 2026-07-16. The owner delegated the final local Turkish
journey to Codex. Environment-specific Phase 2 live-profile evidence remains a separate closure gate
and is never inferred from Phase 2.5 acceptance.

## Evidence

- Canonical Compose PostgreSQL, Redis and MinIO reported healthy; `/v1/health/live` returned HTTP 200.
- Repaired the canonical Dockerfile package-copy ordering. `docker compose ... build web` completed
  and produced `agenthub-web:latest`; the prior `package directory 'config' does not exist` blocker
  no longer occurs. `docker run ... agenthub-web:latest python manage.py check` also passed.
- Frontend: 7 test files and 20 tests passed; TypeScript/Vite production build passed.
- Full SQLite: 741 collected, 712 passed and 29 PostgreSQL-only tests skipped.
- The first SQLite attempt reached 711 passed/29 skipped and then failed when pytest could not access
  the Windows user Temp directory. The unchanged suite was rerun from the beginning with a
  repository-local `--basetemp`; it passed. No test or assertion was weakened.
- Full PostgreSQL/Redis: 741 collected, 736 passed and 5 intentional off-PostgreSQL guard tests
  skipped. PostgreSQL/pgvector, RLS, advisory-lock and Redis paths were exercised.
- Ruff format and lint: 371 files formatted; all checks passed. The previously recorded
  `apps/builder/node_schema.py` formatting drift was normalized without behavior changes.
- Mypy: no issues in 371 source files.
- Django system check: no issues; migration drift: no changes; compileall: passed.
- Tests ran without pytest `-q` and without a pytest timeout.

The integrated suites cover authenticated and unauthorized console flows, tenant isolation,
credential lifecycle, scenario JSON/graph editing, compiler/runtime limits, REST/MCP protocol
separation, OpenAI-compatible adapters, release promotion/rollback and audit/redaction boundaries.

## Authenticated owner-acceptance evidence — 2026-07-16

- Seeded the idempotent demo fixture without `--reset`; no existing demo organization data was
  deleted. Acceptance-only REST/MCP credentials were revoked after the probes.
- Admin organization workspace exposed navigable project, scenario, document-set, consumer,
  artifact, release, membership and run relationships. Auditor showed no mutation buttons.
- An auditor request for another organization's known slug returned 404 without tenant data.
- Scenario Studio opened from the exact RAG scenario with organization/project locked and unrelated
  drafts absent. A complete four-node `agenthub/v1` JSON became the equivalent graph.
- Generate exposed `prompt_ref` and `model_profile_ref`; Format output exposed the governed
  `template_ref` semantics. Backend validation passed with a checksum, JSON round-trip preserved the
  graph and immutable `part9_acceptance:v1` publication succeeded.
- `/v1/chat/completions` and `/v1/responses` returned 200 with bounded compatible envelopes using the
  REST credential. MCP `tools/list` returned 200 with the MCP credential. MCP-on-HTTPS, REST-on-MCP
  and an unbound alias returned controlled 403 errors; missing authentication returned 401.
- The existing demo agent release correctly failed closed because its immutable compiled checksum
  predated the current compiler. A new immutable `assistant:v2` and release were compiled and
  activated without resetting demo data; async invoke returned 202 then completed with output.
- The prior agent release was atomically restored through the audited rollback path, after which the
  new working release was explicitly reactivated. The final active agent release is the working one.
- The acceptance REST token was revoked and returned 401; a replacement was shown once and returned
  200. Both the replacement and acceptance MCP token were revoked during cleanup.
- Audit contained token issue/revoke, protocol denial and release rollback actions; usage records
  correlated successful/denied operations by request ID. Only the intentionally safe token prefix is
  audited. Existing automated tests prove full plaintext and stored token hashes are absent.

## Final review

- Staff engineer: the only runtime packaging change preserves the existing image, command and
  non-root model; product behavior is unchanged and current-behavior documentation now matches it.
- AppSec: no authority, public schema, dependency, credential or network policy changed. The manual
  gates retain cross-tenant denial, protocol separation, redaction and fail-closed disable checks.
- SRE: canonical image build and container Django check pass; health and dependency services were
  observed healthy. Real provider availability, production pooling, alert ownership and rollback
  remain explicit live-environment gates.

## Environment-specific gates transferred to Phase 2 closure

- Real Confluence, generic REST, embedding, OCR and AI-authoring profiles require named endpoints,
  secret references, CA/DNS/firewall decisions, synthetic smoke inputs, retention/privacy approval
  and spend ceilings.
- Production non-owner role/RLS pooling evidence, monitoring/audit review and disable/rollback drills
  require the target environment and a separately approved change window.
- Upload malware/type scanning remains an explicitly accepted Phase 3 residual risk.
