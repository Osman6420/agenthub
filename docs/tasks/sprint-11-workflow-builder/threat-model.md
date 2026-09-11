# Threat Model: sprint-11-workflow-builder

## Assets

Workflow DSL drafts, published `workflow_definition` artifacts, tool binding-role names,
custom-node schemas, operator identity/session, tenant isolation, and the
artifact/compiler/eval/promotion pipeline integrity.

## Actors

Tenant operators (scenario editors, org admins, release managers), platform operators,
malicious/over-privileged operators, and a compromised browser/SPA.

## Entry points

The operator JSON API (`/console/api/builder/`): draft CRUD, diagnostics, node-schema,
publish; the console builder page; and the static SPA bundle.

## Trust boundaries

Browser SPA → backend API (the SPA is untrusted convenience; the backend is authoritative);
draft body → `create_artifact_version` validator on publish; node-schema response → what an
operator may learn about tools (roles only, never endpoints/secrets); operator session →
tenant/role scope.

## Data classifications

Draft DSL is author working state (structure, not secrets — the validator rejects inline
secrets on publish). Binding-role names are internal-but-operator-visible. Tool endpoints,
credentials, and `secret:<name>` values are restricted and never leave the backend.

## Authentication

Reuses the Sprint 1 console authentication (LDAP in production, model backend when LDAP is
disabled). The API is session-authenticated and CSRF-protected. No new auth path, no CORS.
Unauthenticated API calls return 401 JSON (not an HTML login redirect).

## Authorization

Server-side default-deny. Draft read is membership-scoped (`allowed_organization_ids`);
draft create/update/delete and publish require `can_author_scenarios(user, org)`. The
frontend read-only mode is a convenience mirror of the same server decision, never the
enforcement point. Release promotion stays on the existing release-manager path.

## Tenant isolation

Every draft query is bound to the authenticated operator's allowed organizations. A draft
id outside scope is not found / denied. Publish writes the artifact into the draft's own
organization only; the organization cannot be spoofed from client input.

## External systems

None new at runtime. The React Flow SPA is same-origin static assets. The Node/npm build
toolchain is a build-time-only supply-chain surface (pinned lockfile, MIT deps).

## Abuse cases

- An operator crafts a malicious DSL to bypass compiler checks — mitigated: publish routes
  through the same `create_artifact_version` + compiler validation as GitOps.
- The SPA attempts to publish without a role — mitigated: server re-checks role; the client
  read-only flag is not trusted.
- Node-schema is probed to learn tool endpoints/secrets — mitigated: only binding roles +
  public config schema are returned.
- Cross-tenant draft read/write via a guessed id — mitigated: membership-scoped queries.
- CSRF on a mutating call — mitigated: Django CSRF on all unsafe methods.
- Oversized/deeply nested draft body — mitigated: bounded body validation.

## Failure cases

Compiler raises on invalid DSL (returned as structured diagnostics, HTTP 200, no persist);
publish validation failure returns a safe error and writes nothing; audit-write failure on
publish fails closed with the artifact write in the same transaction.

## Logging and audit risks

Do not log raw draft bodies. Audit `builder.draft.create/update/delete/publish` with actor,
org, draft/artifact id, and outcome; publish additionally records the artifact checksum. No
tool endpoints/secrets in any event.

## Mitigations

Single validated publish path; membership + role authorization re-checked server-side;
node-schema role-only disclosure; CSRF + 401/403 JSON; bounded body; deterministic
client-side DSL serialization that the backend re-validates; same-origin static serving with
no CORS.

## Residual risks

An authorized scenario editor can still author a semantically poor (but schema-valid)
workflow — caught later by eval/promotion gates, unchanged from GitOps. The added JS
build toolchain broadens the build-time supply chain. The SPA's client-side validation is
advisory; correctness depends on the backend, by design.

## Required security tests

Unauthenticated 401; wrong-role 403; cross-tenant draft denial; node-schema excludes tool
endpoints/secrets; publish rejects inline secrets via the shared validator; publish is
role-gated and audited; CSRF enforced on mutations; diagnostics never persist.

## Implementation status (2026-07-12)

Implemented and evidenced in [`verification.md`](verification.md):

- Single validated publish path: `publish_draft` → `create_artifact_version` → shared
  `validate_body` (inline-secret rejection + workflow compiler). The builder adds no bypass;
  `test_publish_rejects_inline_secret` confirms a compile-clean but secret-bearing body is
  refused.
- Server-side default-deny authorization re-checked on every call: membership read scope +
  `can_author_scenarios` write gate; 401 (unauthenticated), 403 (wrong role), 404
  (cross-tenant), CSRF enforced on mutations. The SPA's read-only flag is a mirror, not the
  gate.
- Node-schema discloses only binding *role* names + approval flag; tool endpoints,
  definition manifests, and `secret:<name>` references never leave the backend
  (`test_node_schema_exposes_roles_never_endpoints_or_secrets`,
  `test_node_schema_excludes_other_tenant_bindings`).
- Same-origin static serving reusing the console session/LDAP identity — no CORS, no
  token/bearer path, no separate identity or authorization system.
- Bounded draft bodies (256 KiB); audited state changes; no raw draft bodies in logs.

Residual (recorded above): an authorized editor can still author a schema-valid but
semantically weak workflow (caught by the existing eval/promotion gate); the added JS build
toolchain broadens the build-time supply chain (pinned lockfile + `npm ci` CI gate); the
client-side validation is advisory by design (the backend is authoritative). No
headless-browser/live-server smoke was run.
