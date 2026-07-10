# Task Plan: sprint-11-builder-expansion

## Task summary

Extend the existing LDAP-authenticated operator console with governed draft workflow
APIs and a schema-driven visual builder that uses the same compiler, evaluation,
release, promotion, and trace paths as GitOps.

## Background

Sprints 8–10 establish immutable workflow/agent/tool runtime contracts. Sprint 11 adds
an authoring experience, not a parallel runtime or identity system. The plan can be
prepared now; implementation must wait for those schemas and lifecycle contracts to be
verified. ADR-0001 remains authoritative for LDAP identity and custom-console scope.

## Scope

- Tenant-scoped draft workflow CRUD with optimistic concurrency, validation, and audit.
- Compiler diagnostic and schema/registry discovery endpoints for authorized editors.
- A React Flow-style builder integrated into the custom console.
- Node forms generated from approved contract/registry schemas.
- Validate, test, eval, publish, promotion-status, and redacted trace views that call
  existing domain services.
- Safe draft-to-immutable-artifact conversion and GitOps-compatible export/provenance.

## Non-goals

A new identity/role system, browser-side authorization, direct runtime graph editing,
active release mutation, secret/tool-endpoint display or entry, arbitrary code/plugin
upload, bypassing eval/promotion, collaborative real-time editing unless separately
approved, or replacing GitOps.

## Acceptance criteria

- The builder creates only versioned DSL drafts; runtime executes only compiled,
  immutable, release-pinned artifacts.
- LDAP/session identity and existing tenant/role/action authorization protect every
  page and endpoint; cross-tenant IDs and client roles are ignored/denied.
- Forms derive from allowlisted schemas and cannot submit secrets, endpoints, entrypoints,
  unknown node types, or unauthorized tool/custom-node versions.
- Publish uses the same canonical validator/compiler/artifact checksum/eval/promotion
  services as GitOps/commands, with no privileged UI shortcut.
- Concurrent edits produce an explicit conflict instead of silent overwrite; publish
  is idempotent and auditable.
- UI and API safely encode diagnostics/traces and never reveal hidden/redacted fields.

## Affected components

`console`, new draft/API services, identity/tenancy, artifacts, workflows, custom-node
registry, tools, evaluations, releases, agent traces, static frontend/build tooling,
migrations, audit, observability, tests, and docs.

## Interfaces affected

Authenticated internal APIs for drafts, schemas/registry, diagnostics, test/eval/publish,
and trace views; frontend asset/build contract. Any new production frontend dependency
or API contract requires explicit approval and snapshot/version policy.

## Data impact

Add mutable draft and revision/conflict metadata separate from immutable artifacts.
Drafts may contain confidential business logic but never secret values. Define owner,
tenant, retention, deletion, export provenance, and audit behavior.

## Security impact

The browser/API adds XSS, CSRF, IDOR, mass assignment, schema poisoning, stored-content,
dependency/supply-chain, and accidental secret exposure risks. Server validation and
authorization remain authoritative; CSP and safe rendering are required.

## Authorization impact

Reuse LDAP session and existing organization roles. Define explicit permissions for
draft create/read/update/delete, validate/test, eval, publish, promote, and trace view.
Publishing/promotion retains separation of duties and release-manager checks.

## Observability impact

Audit draft mutations, validation/test, publish allow/deny, artifact checksum, and
promotion handoff with actor/tenant/trace and safe reasons. Capture frontend/API errors
without draft bodies, schemas containing sensitive annotations, or trace payloads.

## Migration impact

Additive draft/revision tables and indexes. Frontend assets deploy compatibly with API
versions. Immutable artifact/release data is not rewritten.

## Dependencies

Verified Sprints 8–10 schemas, compiler, registry, eval/promotion, and trace redaction;
ADR-0001; approved frontend architecture; CSP, accessibility, and asset-delivery
decisions. React, TypeScript, and React Flow are approved production dependencies;
implementation still requires version selection, provenance/license/maintenance review,
lockfile consistency, and frontend supply-chain evidence.

## Implementation steps

1. Approve API/versioning, draft lifecycle, permissions, concurrency, frontend, CSP,
   dependency, and accessibility decisions.
2. Add draft/revision models, constraints, migrations, scoped domain services, and audit.
3. Add internal APIs with explicit serializers, CSRF/session protection, pagination,
   ETags/version checks, stable errors, and contract snapshots.
4. Build schema/registry-driven node palette/forms and safe graph editor integration.
5. Wire canonical validate/test/eval/publish/promotion and redacted trace services.
6. Add GitOps export/provenance, operational metrics, and support runbooks.
7. Add security, authorization, browser, accessibility, contract, migration, concurrency,
   and end-to-end tests; update current-state docs after verification.

## Test plan

- Permission matrix and cross-tenant draft/schema/registry/diagnostic/trace/publish denial.
- CSRF, XSS/stored XSS, IDOR, mass assignment, content type, size/depth, unsafe URL,
  schema poisoning, and sensitive-field tests.
- Optimistic concurrency, delete/publish races, idempotent publish, checksum/provenance,
  and no active-release mutation.
- Builder DSL round-trip and compiler parity with GitOps, including invalid graph diagnostics.
- Eval/promotion separation-of-duties and audit-failure rollback.
- API/schema snapshots, frontend unit/integration, keyboard/accessibility, CSP, asset/SRI
  policy where applicable, dependency/secret scans, and browser end-to-end flows.
- Migration compatibility on SQLite/PostgreSQL and production-like draft volume.

## Rollout plan

Deploy APIs read-only, then enable drafts for a small editor cohort with publish
disabled. Enable validate/test, then eval/publish after parity evidence. Promotion
remains a distinct release-manager action. Keep GitOps as the recovery path.

## Rollback plan

Disable builder routes/features while preserving drafts and immutable artifacts. Serve
the existing server-rendered console and GitOps/management flows. Revert frontend assets
and API feature flags together; retain additive schema/audit.

## Risks

- UI convenience can accidentally bypass canonical lifecycle controls.
- Mutable drafts and concurrent editing can cause lost work or publish the wrong revision.
- Schema-driven rendering can still create XSS or expose sensitive registry metadata.
- Frontend dependency/build chain expands supply-chain and patching obligations.

## Open questions

- Frontend build ownership, supported browsers, CSP details, and asset-delivery policy.
- Draft sharing rules and test/eval data visibility.
- GitOps provenance/signing expectations and conflict handling across import/export.
- Accessibility, localization, and manual UX acceptance owners.

## Approved decisions

- The builder uses React, TypeScript, and React Flow as production dependencies, subject
  to implementation-time version, provenance, license, maintenance, vulnerability, and
  lockfile review.
- The frontend is integrated under the existing Django operator console, not deployed
  as a separately authenticated SPA. It reuses the LDAP-backed Django session, CSRF
  protection, and existing server-side tenant/role authorization.
- Drafts autosave after a 5-second debounce and also expose an explicit save action.
  Every write uses a revision/ETag precondition; stale edits produce a visible conflict
  and never silently overwrite a newer revision.
- `project_editor` may create/edit drafts and run validation/tests. `release_manager`
  may run evaluation and publish. Promotion remains a separate release lifecycle action;
  an editor cannot independently promote their draft to production.
- Builder and GitOps use the same immutable artifact schema, checksum, compiler,
  evaluation, and release services. Builder DSL can be exported for GitOps, and an
  imported immutable artifact may seed a new mutable draft. Active releases are never
  edited in place.
- Deleted drafts are soft-deleted for 30 days and then purged. Published immutable
  artifacts and their governed retention are unaffected by draft deletion.
- These decisions, including production use of React, TypeScript, and React Flow subject
  to supply-chain review, were approved by the project owner on 2026-07-10.

## Status

Planned; implementation depends on verified Sprints 8–10 contracts and explicit
approval for production frontend dependencies, internal APIs, and authorization scope.

## Completion criteria

Definition of Done evidence covers LDAP/session reuse, permission/isolation matrix,
canonical compiler/eval/promotion parity, draft concurrency/provenance, XSS/CSRF/IDOR/
mass-assignment defenses, sensitive-data handling, dependency scans, migrations,
accessibility/browser flows, rollback, and required human UX/security review.
