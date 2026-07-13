# Phase 2 · P8 — Document-plane console UI

Authority for scope: [`runtime-and-document-plane-sequence.md`](../../planning/components/runtime-and-document-plane-sequence.md)
§ "P8 — Console UI · WS1 M5". Reuses the existing operator console (LDAP/session auth, role/tenant
scoping) — it is **non-authoritative**: every state change goes through the audited
`apps.documents.services`; the UI adds no capability GitOps/CLI does not already grant.

## Goal

Make the document plane operable from the operator console — per-tenant document upload, listing,
soft-delete, set membership, scenario binding, and purge — role/tenant-scoped and audited, with **no
new egress and no new dependency** (server-rendered Django views like the rest of the console, not a
new SPA).

## Decomposition (each increment additive-migration-safe — no model changes; UI over P2/P4 services)

### P8.1 — Documents list + upload + soft-delete — **IMPLEMENTED (this change)**

- `GET /console/documents/` — lists the operator's document sets and documents (tenant-scoped via
  `allowed_organization_ids`), each document showing version + tombstone state.
- `POST /console/documents/upload/` — multipart upload into an **author-scoped** org selector
  (`DocumentUploadForm`, choices limited to `author_organization_ids`); the view re-checks
  `can_author_scenarios` server-side (defense in depth) and calls `upload_document`.
- `POST /console/documents/<pk>/soft-delete/` — tombstones a document (`soft_delete_document`),
  tenant-scoped (cross-tenant target → 404) and author-gated.
- Nav link added; all actions audited by the underlying services.

### P8.2 — Document sets: create + version + membership + publish — **IMPLEMENTED (this change)**

- `POST /console/document-sets/new/` — create a set (`DocumentSetForm`, author-scoped org) via
  `create_document_set`.
- `GET /console/document-sets/<pk>/` — a set-detail page: versions (newest first) with their
  membership, and, for a **draft** version, an add-member picker (the tenant's active documents) +
  publish action. Tenant-scoped (cross-tenant → 404).
- `POST .../versions/new/` → `create_document_set_version` (draft).
- `POST /console/document-set-versions/<pk>/add-member/` → pins the chosen document's current
  `DocumentVersion` via `add_document_to_set_version` (validated same-tenant, active, draft-only).
- `POST /console/document-set-versions/<pk>/publish/` → `publish_document_set_version` (freeze →
  promotable); an empty version fails gracefully (redirect + `SET_VERSION_EMPTY`, not a 500).
- All author-gated (`can_author_scenarios`) and audited by the services.

### P8.3 — Scenario ↔ document-set binding + ACL grants — **PLANNED**

- Bind/unbind a scenario to a document set (`bind_scenario_document_set` /
  `unbind_scenario_document_set`) and manage consumer ACL grants (`grant_document_set`) — the
  deny-by-default retrieval unit made operable. Binding/grant changes are release-compile inputs, so
  the page notes a recompile is needed to take effect.

### P8.4 — Purge (elevated, destructive) — **PLANNED**

- A separate, confirmation-gated physical purge (`purge_document`), fail-closed on pinned content
  (`DOCUMENT_IN_USE`), audited as an elevated action.

## Non-negotiable constraints

- Non-authoritative UI: no validation/authorization/lifecycle logic in the client; the console views
  re-check authorization server-side and delegate to the audited services.
- Read scope = tenant membership; write actions = `can_author_scenarios` (purge is elevated).
  Cross-tenant targets resolve to 404 via the scoped queryset.
- No new dependency, no new egress, no migration (UI over existing P2/P4 models + services).

## Status

- **P8.1: Implemented + verified** (documents list/upload/soft-delete).
- **P8.2: Implemented + verified** (document-set create/version/membership/publish).
- **P8.3–P8.4: Planned.** No blockers (no dependency/egress gates) — console UI over existing,
  tested services (`bind_scenario_document_set` / `grant_document_set` / `purge_document`).
