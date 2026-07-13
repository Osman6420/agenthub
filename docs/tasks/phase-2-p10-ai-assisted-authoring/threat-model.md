# Threat Model: phase-2-p10-ai-assisted-authoring

## Assets

Tenant/project identity, operator descriptions, candidate DSL, model credentials/endpoints, model
budget, mutable drafts, immutable artifacts and release/runtime state.

## Actors

Authorized scenario authors, read-only operators, unrelated tenant members, platform operators,
malicious/stolen operator sessions, compromised model endpoints and prompt-injected user content.

## Entry points

Authenticated same-origin builder UI and CSRF-protected candidate POST endpoint; platform settings,
immutable `ModelProfile`, secret resolver and outbound model transport.

## Trust boundaries

Browser → Django session/CSRF; organization/project IDs → tenant authorization; description → model
user-message data; platform profile → egress transport; model text → bounded JSON parser → canonical
workflow validator; candidate → explicit draft acceptance → separate publish path.

## Data classifications

Descriptions and candidates may contain confidential internal design text. Endpoint/credential data
is secret/platform-restricted. IDs, stable codes, lengths, token counts and coarse latency are safe
operational metadata when cardinality remains bounded.

## Authentication

Existing Django operator session only. No bearer/CORS/public consumer path is added.

## Authorization

Generation and draft transfer require current `can_author_scenarios` permission for the exact
organization. Projects are resolved inside that tenant. Model profile selection is deployment-side,
not an operator capability. Publish remains separately authorized by the existing builder API.

## Tenant isolation

Foreign organization/project identifiers return not-found/forbidden without metadata. Transient
description/response data is never shared or cached as candidate content across tenants. Rate keys
include actor and organization.

## External systems

Only the immutable platform-configured OpenAI-compatible `ModelProfile`, through ADR-0005 transport.
Live DNS/CA/secret/firewall configuration remains a separate deployment approval.

## Abuse cases

- Denial of wallet through rapid generation requests or many sessions.
- SSRF/credential steering through description, JSON, request fields or model output.
- Prompt injection asking the model to emit secrets, executable fields or unauthorized tools.
- Cross-tenant project IDs or using read-only membership to incur cost/write drafts.
- Oversized/deep JSON, decompression-like structures, HTML/script strings or parser ambiguity.
- Auto-publishing a candidate or treating model output as an authorization decision.
- Logging/tracing confidential description, prompt, response, DSL, endpoint or credential.

## Failure cases

Profile disabled/missing, cache unavailable, DNS/TLS/connect failure, response timeout after send,
HTTP/provider error, malformed/oversized response, invalid DSL, audit persistence failure and
permission revoked between generation and draft acceptance.

## Logging and audit risks

Framework exception logging must receive content-free typed errors. Audit includes no raw input or
output. Pre-call audit failure is fail-closed. Post-call success-audit failure withholds the candidate;
the external cost cannot be rolled back. `outcome_unknown` is terminal and never auto-retried.

## Mitigations

Disabled-by-default profile ID, no caller destination fields, ADR-0005 DNS/IP/TLS/redirect/size
controls, separate system/user roles, strict description/response/JSON depth bounds, canonical
validator/compiler, explicit draft acceptance and separate publish, server authorization rechecks,
CSRF, actor+organization rate limit, content-free errors and audit, no prompt/response persistence,
and deterministic injected providers in tests.

## Residual risks

Rate limits bound but do not eliminate spend; administrators can still intentionally consume budget.
The model may produce low-quality yet valid DSL. Real provider privacy/retention behavior and live
cost ceilings require environment review. In-memory/cache rate limiting depends on Redis availability
and needs an explicit fail-closed policy during implementation.

## Required security tests

Authentication/CSRF/role/cross-tenant denial; caller profile/destination rejection; rate isolation
and boundary; prompt/output redaction; malicious/oversized/deep/malformed responses; inline-secret and
forbidden-field compiler denial; audit fail-closed behavior; no artifact/release before explicit
publish; `outcome_unknown` no retry; live egress disabled in default/test settings.
