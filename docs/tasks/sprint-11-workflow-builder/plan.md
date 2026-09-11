# Task Plan: sprint-11-workflow-builder

## Task summary

Extend the operator console with a visual workflow authoring experience — a React Flow
builder client backed by a governed draft API — **without** introducing a new identity,
authorization, or publish path. The builder produces a versioned workflow DSL and routes
publishing through the existing artifact/compiler/eval/promotion pipeline.

## Background

Sprint 8 compiles immutable workflow DSL artifacts (`workflow_definition`) into runtime
DAGs; Sprint 2 supplies `create_artifact_version` (the single validated authoring path)
and the release compiler; Sprint 1 supplies the LDAP-authenticated console with
membership read-scope and role write-gates. Today, workflow DSL is authored only via
GitOps import or hand-written YAML/JSON. Sprint 11 adds a governed visual surface on top
of those verified contracts. Authoring must not gain any capability the GitOps/compiler
path does not already grant.

## Scope

- A mutable, tenant-scoped `WorkflowDraft` (author working state — **not** a runtime graph
  and **not** an immutable artifact until published).
- An operator JSON API (session/LDAP-authenticated, role-gated, CSRF-protected) for draft
  CRUD, compiler diagnostics, node-schema generation, and publish.
- Compiler diagnostics that reuse `apps.workflows.compiler` verbatim (validate + compile)
  and never persist an artifact.
- Node-schema generation from the builtin node set, org-allowlisted custom nodes, and
  available tool **binding roles** — exposing schema only, never tool endpoints or secrets.
- Publish that calls `create_artifact_version(workflow_definition, ...)` and optionally
  compiles a candidate release through the existing compiler (no bypass).
- A React Flow SPA (`frontend/`, Vite + React + TypeScript) served as Django static assets
  and mounted in a role-gated console template.

## Non-goals

Runtime graph mutation, a second authoring/publish path that bypasses artifact validation
or the release compiler, exposing tool endpoints/secrets/credentials in the UI, a separate
identity/authorization system, consumer-facing builder access, arbitrary code execution
from the canvas, or editing already-published immutable artifacts in place.

## Acceptance criteria

- The builder creates a versioned DSL, not a runtime graph. Publishing produces an
  immutable `workflow_definition` `ArtifactVersion`; runtime compilation stays in the
  existing compiler.
- Publish uses the same `create_artifact_version` → `compile_release` → eval → promote path
  as GitOps; it grants no new capability and enforces the same validation.
- The UI never shows tool endpoint URLs or secret values; the node-schema API returns only
  binding roles and public config schema.
- The builder reuses the Sprint 1 console LDAP identity and role/tenant authorization; it
  introduces no separate identity or authorization path. Read is membership-scoped;
  create/update/delete/publish require `can_author_scenarios` in the target organization.

## Affected components

New `apps.builder` (model, services, API, migration); `apps.console` (nav + builder page
template + URL include); `apps.artifacts`/`apps.workflows` (reused, not modified);
`config` settings/urls; a new `frontend/` build; `.github/workflows/ci.yml` (Node build
step); docs.

## Interfaces affected

New operator JSON API under `/console/api/builder/`. No change to the public consumer
gateway, MCP, or any existing artifact/release/eval contract. New draft persistence.

## Data impact

Add a mutable `WorkflowDraft` (organization-scoped, JSON body = workflow DSL, author
attribution, optional link to the last published artifact). No secrets are stored; draft
bodies are author-supplied DSL structure. Retention: drafts are operator working state and
may be deleted by authors; no automated purge in this increment.

## Security impact

The builder is an authoring surface; its trust boundary is the same as GitOps import. All
writes revalidate through `create_artifact_version` (schema + secret-rejection + checksum).
The node-schema endpoint is an information-disclosure boundary and must expose only public
schema + binding roles. CSRF applies to all mutating operator calls; unauthenticated calls
return 401 JSON, unauthorized calls 403 JSON. React Flow SPA is same-origin, session-auth.

## Authorization impact

Draft read is membership-scoped (`allowed_organization_ids`); draft create/update/delete
and publish require `can_author_scenarios(user, org)`. Cross-tenant access to a draft is
denied. Compiling/promoting a release remains gated by the existing release-manager path.

## Observability impact

Audit `builder.draft.create/update/delete` and, as a security-sensitive state change,
`builder.draft.publish` with the resulting artifact id/checksum. No raw draft bodies in
logs. Diagnostics are synchronous and unaudited (read-only validation).

## Migration impact

One additive migration creating `WorkflowDraft`. No change to existing tables.

## Dependencies

Approved new production frontend dependencies (project owner, 2026-07-11): Node/npm build
toolchain, Vite, React, React DOM, and React Flow (`@xyflow/react`). Verified Sprint 2
artifact/compiler and Sprint 8 workflow compiler contracts. Supply-chain review: all are
MIT-licensed, widely used, actively maintained; the build output is served as static
assets and adds no Python runtime dependency.

## Implementation steps

1. Create task plan/threat-model/verification docs and record the frontend-dependency
   approval.
2. Add `apps.builder` with `WorkflowDraft` + additive migration.
3. Implement services: node-schema builder, diagnostics (reuse compiler), publish (reuse
   `create_artifact_version` + optional release compile).
4. Implement the operator JSON API with LDAP/role/tenant authz, CSRF, and audit; wire URLs,
   console nav, and settings.
5. Add backend tests (happy/invalid/authn/authz/cross-tenant/redaction/diagnostics/publish)
   and run all Python gates; commit.
6. Scaffold the React Flow SPA (`frontend/`), build the builder UI, integrate Django static
   serving + console template, add the CI Node build step.
7. Verify the npm build and gates; update current-state docs; commit.

## Test plan

- Draft CRUD happy path; invalid/oversized body rejected; unknown fields rejected.
- Unauthenticated → 401; wrong-role → 403; cross-tenant draft access → denied.
- Diagnostics returns structured errors for an invalid DSL and success for a valid one,
  without persisting an artifact.
- Node-schema returns builtin + org custom nodes + binding roles and **no** endpoints or
  secrets.
- Publish creates a `workflow_definition` artifact via the shared path; secret-bearing
  bodies are rejected by the shared validator; publish is role-gated and audited.
- Frontend: `npm ci && npm run build` succeeds; the bundle mounts and calls the API.

## Rollout plan

Ship the backend API first (usable by GitOps-adjacent tooling and tests). Then ship the
SPA behind the existing role-gated console. No data migration risk; drafts are additive.

## Rollback plan

Remove the console nav entry and the SPA; the draft table is additive and inert if unused.
No published artifact or release is affected by disabling the builder.

## Risks

- A visual builder can tempt a second, weaker publish path — mitigated by routing publish
  through `create_artifact_version` only.
- Node-schema disclosure could leak tool endpoints/secrets — mitigated by exposing roles +
  public schema only.
- Adding a JS build toolchain enlarges the supply-chain and CI surface — mitigated by
  pinned lockfile, MIT deps, and a Node build gate.

## Approved decisions

- The project owner approved the **Full React Flow SPA** on 2026-07-11: new production
  frontend dependencies with a **pinned** Node/npm toolchain, Vite, React, React DOM, and
  `@xyflow/react`, with the **lockfile committed**, plus a CI Node build step. This is
  analogous to the Sprint 10 LangGraph approval.
- The builder reuses console LDAP identity + role/tenant authorization and the existing
  artifact/compiler/eval/promotion path; it introduces no alternate identity, authorization,
  or publish path.
- The **workflow DSL + governed backend API are the source of truth**. The frontend MUST
  NOT contain authoritative validation, authorization, lifecycle, promotion, or execution
  logic. Every draft save, compile, validate, publish, and run operation goes through the
  existing tenant-scoped backend services. The client renders backend diagnostics/state and
  offers convenience only.
- The built frontend is served **same-origin through Django**, reusing the existing
  LDAP/session identity and role/tenant authorization. No separate authentication system and
  **no public CORS surface** are introduced.
- **Earlier plan (consolidated).** The originally-approved Sprint 11 plan (2026-07-10, then
  named `sprint-11-builder-expansion`, now archived under
  [`docs/planning/archive/`](../../planning/archive/README.md)) also approved React /
  TypeScript / React Flow as production dependencies and recorded these authoring decisions:
  optimistic concurrency (revision/ETag precondition + visible conflict, never a silent
  overwrite), autosave after a 5-second debounce, 30-day draft soft-delete then purge, a
  distinct `project_editor` draft-authoring permission, builder-embedded validate/test/eval/
  publish/trace views, and GitOps draft export / import→draft seed. Those decisions remain
  valid intent but were **not all delivered** in this increment — see the reconciliation
  below.

## Minimum frontend feature set (owner-specified, 2026-07-11)

Workflow draft create/edit/save; node palette + drag/drop canvas; typed edge connections;
node configuration panel; backend compile/validation errors displayed on the graph;
unsaved-change protection; read-only mode driven by role; deterministic DSL serialization;
frontend unit tests plus one end-to-end builder flow.

## Scope reconciliation — consolidation & delivered vs deferred

This record is the **single canonical Sprint 11 task plan**. It consolidates the earlier
duplicate `sprint-11-builder-expansion` plan (same sprint, richer originally-approved scope),
which is now archived with a supersession pointer. There is one active Sprint 11 folder.

**Delivered and verified in this increment:** the governed draft API (`apps.builder`) —
`WorkflowDraft` + CRUD + compiler diagnostics + node-schema + shared-path publish, LDAP/role/
tenant authz, CSRF, audit, additive migration — and the React Flow SPA (draft create/edit/
save, palette + drag/drop canvas, typed edges, schema-driven config panel, backend
diagnostics on the graph, unsaved-change protection, role-driven read-only, deterministic DSL
serialization, unit + one e2e test). Evidence in [`verification.md`](verification.md).

**Deferred — reclassified into [Phase 2](../../planning/phase-2-plan.md).** Given the Phase 2
decision to repurpose the builder toward AI-assisted authoring + a preview surface (small DSL
edits), the following originally-planned items are moved to Phase 2 rather than built
speculatively now: optimistic concurrency (ETag/revision + `409` conflict), autosave debounce,
30-day draft soft-delete/purge, GitOps draft export / import→draft seed, an artifact detail/
preview view for endpoint- and AI-produced artifacts, builder-embedded test/eval/trace panels
(today they link to the existing console screens), a Content-Security-Policy header, and a
distinct `project_editor` permission (today draft authoring reuses `can_author_scenarios`).
None of these are required for the delivered scope to be safe or correct; each is tracked in
the Phase 2 plan for a decision under the trimmed-builder direction.

## Status

Implemented and Verified (2026-07-12) for the **delivered scope above**; enhancements from the
originally-approved plan are **deferred to Phase 2** (see the reconciliation). Delivered in two
increments.

**Backend (`apps.builder`)** — the tenant-scoped mutable `WorkflowDraft`, the operator JSON
API (`/console/api/builder/`) for draft CRUD + compiler diagnostics + node-schema generation
+ publish, all reusing the console LDAP/session identity and Sprint 1 role/tenant
authorization, with CSRF, 401/403 JSON, and audited state changes. Diagnostics and publish
route through the shared `validate_body` / `create_artifact_version` path; the node-schema
endpoint exposes only binding *roles* + public config schema (no tool endpoints/secrets).
Additive migration `builder.0001`. SQLite 364 passed / 2 skipped; PostgreSQL affected-app
run 46 passed.

**Frontend (`frontend/`)** — a React Flow SPA (Vite + React + TypeScript, pinned lockfile)
served same-origin as Django static assets (`apps/builder/static/builder/`) and mounted in
the role-gated console builder page. It provides draft create/edit/save, a node palette with
drag/drop + click-to-add, typed edge connections (auto-typed condition branches +
`isValidConnection`), a schema-generated node config panel, backend diagnostics shown on the
graph, `beforeunload` unsaved-change protection, role-driven read-only mode, and
deterministic DSL serialization. The client holds **no** authoritative validation,
authorization, lifecycle, promotion, or execution logic — every operation is a backend
round-trip. `npm ci`/typecheck/`vitest` (11 tests incl. one e2e builder flow)/`vite build`
all pass; `findstatic` resolves the bundle. See [`verification.md`](verification.md).

## Completion criteria

Definition of Done evidence covers draft authorization/isolation, redaction (no tool
endpoint/secret disclosure), shared-publish-path enforcement, diagnostics correctness,
additive migration, the verified frontend build, and final application-security review.
