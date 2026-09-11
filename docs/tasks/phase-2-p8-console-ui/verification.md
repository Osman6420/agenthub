# Verification: phase-2-p8-console-ui

## Status

**P8.1–P8.4 Verified 2026-07-13.** Server-rendered console UI reuses LDAP/session auth and
role/tenant scoping. No new dependency, egress or migration. P8.3 also closes an owner-approved P4
authorization gap: document-set retrieval now requires an effective same-tenant consumer grant.

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

## Acceptance criteria mapping (P8.3)

- Binding and unbinding are author-gated, tenant-scoped and audited.
- Consumer grants are selected from active same-tenant consumers; free-form principal input is not
  accepted. Grant and revoke are audited.
- Foreign principals are rejected; foreign binding/grant object ids return 404; auditors receive
  403. Covered by `test_document_acl_console.py` (6 tests / 8 parameterized cases).
- Real PostgreSQL/pgvector retrieval requires the authenticated consumer's explicit grant;
  `test_grant_is_required_and_is_consumer_specific` covers grant, no grant and no principal.

## Acceptance criteria mapping (P8.4)

- Purge requires organization/platform admin, a tombstoned document and an exact logical-id
  confirmation. Cross-tenant targets return 404.
- The audited service retains its `DOCUMENT_IN_USE` refusal for pinned content.

## Checks and evidence

| Check | Command | Result |
| --- | --- | --- |
| Format | `ruff format --check .` | Pass — 306 files |
| Lint | `ruff check .` | Pass |
| Type | `mypy apps config` | Pass — 305 files |
| Django check | `manage.py check` | Pass — 0 issues |
| Migration drift | `makemigrations --check --dry-run` | Pass — no changes (no migration) |
| Targeted P8.1 | `pytest apps/console/tests/test_documents_console.py` | 5 passed |
| Targeted P8.2 | `pytest apps/console/tests/test_document_sets_console.py` | 5 passed |
| Targeted P8.3 | `pytest test_document_acl_console.py test_document_sets_console.py test_bindings.py` | 18 passed |
| Targeted P8.4 + P8.3 | `pytest test_documents_console.py test_document_acl_console.py` | 14 passed |
| Final SQLite | `pytest -q --basetemp=.tmp/pytest` (`config.settings.test`) | 511 passed, 21 skipped (PostgreSQL-only) |
| Final PostgreSQL | `pytest -q --create-db --basetemp=.tmp/pytest-pg` (`config.settings.local` + MCP/metrics flags) | 530 passed, 2 skipped (off-PG guards) |

Baseline before P8 (P7.2): SQLite 492 passed / 20 skipped; PostgreSQL 510 passed / 2 skipped.
Cumulative P8 delta: +19 console tests plus one PostgreSQL ACL retrieval test.

## Checks not run

- No headless-browser/live-server smoke of the console pages (verified by Django test client +
  server-rendered template render); manual UI smoke is recommended before demo but not required for
  the automated gate.
- No headless-browser confirmation-dialog test; exact confirmation is covered at the Django view.

## Final reviews

- Staff engineer: P8 is complete over server-rendered, non-authoritative views and audited services;
  no model/migration/dependency/egress change. Retrieval-provider implementations now receive an
  optional `consumer_id`; configured custom providers must accept the extended keyword.
- Application security: read is tenant-membership-scoped; upload/soft-delete re-check
  `can_author_scenarios` server-side (the scoped form choices are UI convenience only); cross-tenant
  targets 404 via the scoped queryset; all state changes are audited by the services; uploads use the
  service's MIME allowlist + size cap.
- SRE: no external service or migration; tests are hermetic except the deliberate local PostgreSQL
  gate. Revoking a grant affects subsequent retrieval immediately; binding changes require compile.
