# Threat Model: comprehensive-live-application-qa-2026-09-04

## Assets

- Existing local tenant data, immutable artifacts/releases, uploaded document bytes and indexes.
- Operator session credentials, consumer bearer tokens and any configured provider secret refs.
- Tenant isolation, exact-responsibility authorization and audit/usage evidence.
- Availability and correctness of the running local Compose stack.

## Actors

- Platform/organization administrator.
- Exact scenario editor, release manager, document-set manager, runtime operator and approver.
- Same-tenant member without the required exact responsibility.
- Foreign-tenant actor.
- REST or MCP consumer.
- QA operator driving automated and real-browser tests.

## Entry points

- `/console/`, its forms and JSON endpoints.
- `/v1/responses`, `/v1/chat/completions`, `/v1/runs/*`, `/mcp/` and `/internal/metrics`.
- PDF upload/object storage, ingestion queues, pgvector stores and Celery transitions.
- Local management commands and the guarded Playwright test launcher.

## Trust boundaries

- Browser affordances to server-side session/CSRF/object authorization.
- Bearer credentials to protocol, consumer, binding, alias and capability authorization.
- Uploaded filename/bytes to parser, object storage, chunking and index services.
- Web admission to queue/worker execution under current code and tenant context.
- Model/embedding/connector profiles to optional external network boundaries.
- Application actions to redacted logs, metrics, usage and security/business audit.

## Data classifications

- Supplied PDFs and extracted chunks: user-supplied local test content; do not reproduce in reports.
- Credentials/tokens/cookies/provider secrets: secret; never persist in documentation or captures.
- Prompts/model responses: potentially confidential; record only safe result/status metadata.
- Object identifiers, status, safe error codes, request IDs and aggregate counts: permissible bounded
  QA evidence.

## Authentication

Use repository-created local test identities and supported session/bearer mechanisms. Do not bypass
authentication or copy secrets into shell history, reports or screenshots.

## Authorization

Every visible/hidden control assertion is paired with server enforcement evidence where practical.
Client-supplied tenant, parent, role or responsibility values are treated as untrusted.

## Tenant isolation

Use explicit second-tenant objects for non-disclosing 404/denial checks. Do not infer isolation only
from navigation visibility. Worker, retrieval and audit evidence must remain tenant-bound.

## External systems

PostgreSQL/pgvector, Redis and MinIO are local Compose services. No real model, embedding, OCR,
connector or tool egress is initiated unless an already approved governed profile is safely shown as
ready and the call uses synthetic bounded input.

## Abuse cases

- Forged object IDs, tenant/parent fields or direct POSTs bypassing hidden UI controls.
- REST credentials used on MCP or MCP credentials used on REST.
- Replayed idempotency keys with conflicting payloads.
- Oversized/malformed DSL or uploads causing unsafe errors or partial state.
- A stale worker executing old code after web source changes.
- Sensitive document, prompt, token, endpoint or secret data leaking through UI, logs or audit.
- Test cleanup accidentally deleting pre-existing local data.

## Failure cases

- Missing provider/profile/grant/index/release/binding blocks dependent steps.
- Worker incompatibility or unavailable queue leaves async work non-terminal.
- Parser/ingestion failure leaves immutable source data but must not activate partial content.
- Browser/UI action fails without useful feedback while the server rejects or errors.
- Baseline test failure prevents the mandatory browser gate from being treated as verified.

## Logging and audit risks

Test actions intentionally create audit/usage records. Evidence inspection is limited to stable
event names, safe IDs, decision/outcome and request/trace correlation. Logs are searched for secret
patterns and unexpected tracebacks without copying sensitive lines into the report.

## Mitigations

- Preserve data; do not run reset, physical purge or destructive migration commands.
- Refresh workers non-destructively before async evidence.
- Use the guarded browser fixture for automated role tests and dedicated synthetic records for live
  checks.
- Stop dependent claims at an unmet governed prerequisite.
- Capture only redacted paths/status/request IDs; disable trace/video/HAR/body capture.
- Review targets before any cleanup and prefer retaining clearly named QA records.

## Residual risks

- Local deterministic providers do not prove production provider behavior, privacy, spend or network
  policy.
- Local admin/database ownership does not by itself prove production non-owner RLS deployment.
- Manual accessibility/UX review is bounded and is not a formal WCAG conformance audit.
- Full performance, soak, chaos and concurrent multi-user testing are outside this pass unless
  existing automated tests cover them.

## Required security tests

- Logged-out/session authentication denial and CSRF-protected mutation behavior.
- Exact-responsibility success plus same-tenant unassigned/neighbor and cross-tenant denial.
- REST/MCP protocol separation; unbound/wrong alias/capability denial.
- Direct forged GET/POST/object IDs return stable non-disclosing 401/403/404 without 500/traceback.
- Idempotency replay and conflict behavior.
- Upload/parser limits and safe failure status where exercised.
- Audit/log/metrics evidence contains no tokens, cookies, prompt, provider response or document bytes.
