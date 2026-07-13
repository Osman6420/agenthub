# Verification: phase-2-p8-console-ui

## Status

**P8.1 + P8.2 Verified 2026-07-13.** Automated evidence only; server-rendered console UI reusing the
existing LDAP/session auth + role/tenant scoping. No new dependency, no egress, no migration. P8.3–P8.4
(binding/grants, purge) are **not implemented** — planned follow-ups with no approval gate.

## Acceptance criteria mapping (P8.1)

- **Tenant-scoped read:** `test_documents_list_is_tenant_scoped` — an org-A operator sees org-A
  documents/sets and never org-B's (scope from `allowed_organization_ids`).
- **Author-gated upload + server-side re-check:** `test_author_can_upload_document` (PROJECT_OWNER
  uploads → `Document`/`DocumentVersion` created + `documents.document.upload` audit event);
  `test_upload_denied_for_non_author` (AUDITOR → the org is outside author scope → no document
  created).
- **Soft-delete author-gated + audited:** `test_soft_delete_tombstones_document`.
- **Cross-tenant defense:** `test_cross_tenant_soft_delete_is_not_found` — an org-A operator cannot
  soft-delete an org-B document (404, target unchanged).
- **Non-authoritative:** all writes route through the audited `apps.documents.services`; the view adds
  no new authorization surface.

## Acceptance criteria mapping (P8.2)

- **Author can create a set:** `test_author_can_create_document_set`; a non-author cannot
  (`test_non_author_cannot_create_set`).
- **Full version lifecycle:** `test_full_set_version_lifecycle` — open draft version → add a member
  (pins the document's current `DocumentVersion`) → publish → `promotable`.
- **Graceful failure:** `test_publish_empty_version_fails_gracefully` — publishing an empty version
  redirects with `SET_VERSION_EMPTY` (no 500) and leaves the version `draft`.
- **Cross-tenant defense:** `test_cross_tenant_set_detail_is_not_found` — a set in another tenant is
  404 for the operator.

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Format | `ruff format --check .` | Pass — 305 files |
| Lint | `ruff check .` | Pass |
| Type | `mypy apps config` | Pass — 304 files |
| Django check | `manage.py check` | Pass — 0 issues |
| Migration drift | `makemigrations --check --dry-run` | Pass — no changes (no migration) |
| Targeted P8.1 | `pytest apps/console/tests/test_documents_console.py` | 5 passed |
| Targeted P8.2 | `pytest apps/console/tests/test_document_sets_console.py` | 5 passed |
| Final SQLite | `pytest -q` (`config.settings.test`) | 502 passed, 20 skipped (pgvector) |
| Final PostgreSQL | `pytest -q --create-db` (`config.settings.local` + MCP/metrics flags) | 520 passed, 2 skipped (off-PG guards) |

Baseline before P8 (P7.2): SQLite 492 passed / 20 skipped; PostgreSQL 510 passed / 2 skipped.
Cumulative P8 delta: +10 console document-UI tests (P8.1 5 + P8.2 5).

## Checks not run

- No headless-browser/live-server smoke of the console pages (verified by Django test client +
  server-rendered template render); manual UI smoke is recommended before demo but not required for
  the automated gate.
- P8.3–P8.4 UI (scenario binding + ACL grants, elevated purge) is not implemented.

## Final reviews

- Staff engineer: server-rendered views (documents + document-set lifecycle) + two forms + two
  templates + a nav link, reusing the established console scoping/audit pattern; no model change, no
  migration, no dependency. Set membership pins the chosen document's current `DocumentVersion`
  through the immutability-preserving service.
- Application security: read is tenant-membership-scoped; upload/soft-delete re-check
  `can_author_scenarios` server-side (the scoped form choices are UI convenience only); cross-tenant
  targets 404 via the scoped queryset; all state changes are audited by the services; uploads use the
  service's MIME allowlist + size cap.
- SRE: no new surface beyond console routes; hermetic (in-memory object store in tests); trivially
  reversible.
