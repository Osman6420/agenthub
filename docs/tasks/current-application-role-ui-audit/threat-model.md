# Threat Model: current-application-role-ui-audit

## Assets
Tenant-scoped control-plane data, documents, scenarios, releases, consumers, runs, credentials, and audit records.

## Actors
Unauthenticated visitor; platform admin; organization admin; editor/author; releaser; approver; auditor; document manager; scoped responsibility roles; consumer/API identities.

## Entry points
Operator console, builder API, public REST/MCP surfaces, management commands, and local Compose services.

## Trust boundaries
Browser to Django session/CSRF boundary; operator identity to organization membership; console to domain services; workers to PostgreSQL/Redis/object storage; public consumer authentication to scenario capability authorization.

## Data classifications
Local demo data, tenant metadata, document content, hashed/secret-backed credentials, audit/security events, and operational health data.

## Authentication
Console session authentication is reviewed. Passwords, tokens, cookies, and browser storage are not inspected or reported.

## Authorization
Server-side action, object, tenant, and field authorization remains authoritative; hidden UI controls are not treated as enforcement.

## Tenant isolation
Lists and object details must remain scoped to the active authorized organization. Two-way cross-tenant probing is limited to safe read-only project URLs; both directions must return non-disclosing 404 responses.

## External systems
Local PostgreSQL, Redis, MinIO, workers, and the explicitly authorized Gemini model/embedding service. Other production or uncontrolled external egress is not authorized.

## Abuse cases
Direct URL access to hidden actions; forged parent/tenant identifiers; mutation by read-only roles; role escalation through membership UI; secret/endpoint disclosure; unsafe document/tool/provider operations.

## Failure cases
Stale frontend bundle, missing workers, unapplied migrations, unavailable credentials, external-provider absence, seeded-data drift, and misleading UI success despite backend failure.

## Logging and audit risks
Manual mutations and live provider calls could generate security/business audit events and provider-side request metadata. Evidence must avoid credentials, tokens, cookies, document bodies, prompts beyond synthetic test text, or unnecessary personal data.

## Mitigations
Use the supported non-destructive startup path; verify live state; prefer disposable demo records and synthetic prompts; test denials; inspect safe bounded logs only when needed; pass the Gemini key through process/container environment only; never print or persist the value; report redacted evidence.

## Residual risks
Representative browser testing cannot prove every authorization branch. Bidirectional project isolation passed, but a confirmed same-tenant cross-scenario run-metadata disclosure remains for exact-scenario runtime operators. Connector egress remains unverified because no governed profile/grant/credential is available.

## Required security tests
Logged-out redirect; role-gated navigation/action visibility; safe direct-route denial samples; active-organization and exact-object scoping; no visible secret-bearing fields in reviewed pages. Add regression coverage for two scenarios in one tenant where the actor has runtime responsibility on only one.
