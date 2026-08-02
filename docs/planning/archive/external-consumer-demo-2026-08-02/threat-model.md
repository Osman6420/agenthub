# Threat Model: external-consumer-demo

## Assets
Gemini API key, consumer bearer tokens, operator password, tenant-scoped documents, run outputs, and audit history.

## Actors
Local demo operator, external-demo consumers, AgentHub services, Wikipedia, and Gemini.

## Entry points
Standalone loopback HTTP server, its restricted `/agenthub/*` proxy, AgentHub `/v1/*`, and the bootstrap management command.

## Trust boundaries
Browser to demo server; demo server to AgentHub; bootstrap to Wikipedia; AgentHub model egress to Gemini; consumer/scenario/document-set tenant boundaries.

## Data classifications
Wikipedia text is public. Tokens, password, and Gemini key are secrets. Run prompts/outputs are local demo data.

## Authentication
AgentHub data plane uses existing hashed bearer-token authentication. Operator console uses the generated local password. Demo server has no remote authentication and therefore binds only to loopback.

## Authorization
Each consumer is bound only to approved scenarios with `workflow_run`; RAG also requires exact consumer and scenario document-set retrieve grants.

## Tenant isolation
All created rows use the dedicated `external-demo` organization. Existing model validation and PostgreSQL/RLS predicates remain authoritative.

## External systems
Wikipedia HTTPS API/page content and Gemini OpenAI-compatible HTTPS endpoint. Destinations are fixed by code/profile, not caller input.

## Abuse cases
- Token theft through source control, logs, URL parameters, browser storage, or proxy errors.
- Proxy used as an open relay or to reach console/internal endpoints.
- SSRF/redirect/oversized response through Wikipedia bootstrap.
- Cross-consumer scenario invocation or document retrieval.
- Prompt injection from untrusted Wikipedia content.

## Failure cases
Wikipedia/Gemini timeout, malformed content, absent secret, failed index build, unavailable worker, partial bootstrap, and background run timeout.

## Logging and audit risks
Never log Authorization headers, tokens, passwords, Wikipedia body, or Gemini key. Existing gateway/audit records use safe identifiers and redacted output.

## Mitigations
- Fixed HTTPS Wikipedia hostname/path, DNS/public-address validation where applicable, no redirects, bounded timeout/body.
- Loopback bind, strict route allowlist, request/body limits, header allowlist, no caching, CSP and referrer policy.
- Secrets only in process environment or gitignored local config; one-time display.
- Transactional/idempotent creation, immutable release pins, least-privilege bindings/grants.
- Existing system prompt separates untrusted retrieved context; citations expose provenance, not raw hidden chunks.

## Residual risks
Local malware or another process under the same OS account can read local demo credentials. External services receive the grounded context required for answering. Wikipedia content can change between bootstraps.

## Required security tests
Denied unbound alias, proxy path rejection, loopback-only bind, no secret in tracked files/output fixtures, cross-consumer RAG denial, and safe handling of upstream errors.
