# Threat Model: sprint-11-builder-expansion

## Assets

Operator sessions, LDAP identity/roles, tenant drafts and business logic, schemas and
registry metadata, immutable artifacts/releases, evaluation evidence, tool/custom-node
permissions, traces, audit history, frontend supply chain, and publish integrity.

## Actors

Editors, release managers, approvers, platform admins, auditors/support staff, malicious
tenant users, compromised operator browsers/accounts, and dependency attackers.

## Entry points

Console pages/static assets, draft/schema/registry/diagnostic/test/eval/publish/trace APIs,
JSON/DSL import/export, browser storage, form fields, diagnostics and trace rendering,
LDAP/session/CSRF boundaries, and frontend build pipeline.

## Trust boundaries

Browser to authenticated console API; LDAP groups to server roles; draft input to
schema/compiler; registry schema to UI renderer; mutable draft to immutable artifact;
publish to eval/promotion; backend diagnostics/traces to DOM; package registry to built
frontend assets.

## Data classifications

Sessions/CSRF material and secrets are restricted. Drafts, schemas, eval inputs,
diagnostics, and traces may be confidential/PII. Artifact metadata and audit are
internal/integrity-sensitive. Secret values and raw credentials are prohibited.

## Authentication

Reuse ADR-0001 LDAP-backed Django sessions with secure cookie, timeout, logout, and
CSRF protections. No SPA-issued identity, client role, tenant header, or browser storage
token becomes authoritative.

## Authorization

Every endpoint and object enforces action, role, organization, project, scenario, and
field authorization server-side. Validate/test/publish/promote/trace are distinct
permissions. Publish and promotion retain separation of duties.

## Tenant isolation

Drafts, revisions, schemas, registry entries, artifacts, evals, releases, and traces are
queried through authoritative tenant scope. Enumeration-resistant errors and scoped
choice lists prevent cross-tenant discovery and reference submission.

## External systems

LDAP, frontend package/build registry, CI/image/static asset delivery, Postgres,
workers, model/retrieval providers used by tests/evals, telemetry, and GitOps export.
No arbitrary browser or server egress is introduced.

## Abuse cases

- IDOR/mass assignment changes tenant, owner, role, artifact, tool, or release fields.
- Stored/reflected/DOM XSS through labels, DSL, schemas, diagnostics, traces, or comments.
- CSRF publishes/deletes/tests a draft or triggers costly evaluation.
- Schema/registry poisoning renders secret fields, endpoints, HTML, or unauthorized nodes.
- Race swaps or modifies a draft between review, eval, checksum, and publish.
- UI calls a hidden shortcut to bypass compiler, eval, promotion, or audit.
- Malicious dependency/build asset steals sessions or changes published DSL.
- Sensitive drafts/traces leak through logs, browser storage, caches, errors, or exports.

## Failure cases

LDAP/session expiry mid-edit, stale schema/frontend/API version, concurrent save/delete/
publish, partial asset rollout, compiler/eval timeout, audit failure, browser crash,
oversized draft, and GitOps export/import mismatch.

## Logging and audit risks

Validation errors, client telemetry, request bodies, and traces can contain full drafts,
PII, or secrets pasted by mistake. Log stable IDs, revision/checksum, field paths, sizes,
actions, and safe reasons. Audit mutation/publish decisions; never store session tokens
or full drafts in telemetry.

## Mitigations

Server-side scoped services and explicit serializers; CSRF and secure sessions; output
encoding and sanitized/structured rendering; CSP; schema allowlists; no raw HTML/eval;
size/depth limits; optimistic revision/checksum locks; transactional immutable publish;
canonical compiler/eval/promotion services; sensitive-field suppression; no persistent
browser secrets; dependency pin/scan/provenance; staged compatible asset/API rollout.

## Residual risks

A compromised authorized editor can create harmful but schema-valid workflows within
their scope, subject to review/eval gates. Frontend dependencies remain a supply-chain
surface. Diagnostics and redacted traces can reveal business logic. LDAP account/group
compromise remains high impact.

## Required security tests

Permission matrix and cross-tenant IDOR; role/tenant/owner mass assignment; CSRF for all
mutations; stored/reflected/DOM XSS across DSL/schema/diagnostics/traces; CSP; schema
poisoning and secret/endpoint field suppression; draft revision TOCTOU and publish
idempotency; canonical gate bypass denial; audit failure rollback; session expiry;
sensitive cache/log/browser-storage tests; dependency/secret scans; and GitOps checksum/
provenance round-trip.
