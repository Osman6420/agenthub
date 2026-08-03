# Verification: scenario-studio-authoring-journey-closure-part-2

## Part 2A automated evidence

- Ruff format/check passed for the changed builder Python files and migration.
- `pytest apps/builder/tests/test_services.py apps/builder/tests/test_api.py -q`: 75 passed.
- `manage.py makemigrations --check --dry-run builder`: no changes detected.
- mypy passed for builder services, API, and models.
- Focused governed-profile/manifest/draft/App frontend run: 21 tests passed across 5 files.
- TypeScript `tsc --noEmit` passed.
- Vite production build passed; 185 modules transformed.
- `builder.0007_artifactdraft_governed_profiles` applied successfully to the local database.
- Live health returned HTTP 200 after the controlled Compose web restart.

## Part 2A live browser evidence

- Existing `external-demo.retrieval:v1` opened automatically as the structured **Arama ayarları**
  form after exact-version selection.
- `mode`, `top_k`, score, hybrid weights, reranker and summary-routing controls were editable for the
  authorized scenario author after the web role loaded the new backend capability projection.
- A temporary client-only `top_k` change revealed the required change-description field and immutable
  publish action; the value was restored and no live artifact version was published.
- The Drafts view displayed **Yeni parçalama / arama profili** with canonical chunking defaults and
  closed structured fields. No live draft was created during acceptance.

## Security/authorization evidence

- API/service tests cover viewer denial, tenant-scoped preview/source-copy, audit presence, canonical
  invalid range/unknown-field/hybrid-weight rejection, and immutable N+1 publication.
- Browser capability flags only control edit affordances. Draft creation, update and publication
  continue to require the existing server-side exact scenario author decision.
- Profile bodies are never rendered as HTML or written to audit/log records by this change.

## Part 2A residual items

- Existing retrieval `metadata_filter` values are preserved but not editable in Part 2A; a bounded
  filter builder remains Part 2B work.
- Staged-index six-selector integration and safe platform/model/OCR projections remain unverified and
  are not claimed complete.
