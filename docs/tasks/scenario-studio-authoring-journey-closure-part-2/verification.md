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

## Part 2B automated evidence

- `pytest apps/console/tests/test_document_workspace_console.py -q`: 7 passed before the final
  client-only selector attributes; the exact changed profile projection/default test passed again
  after the final least-privilege and selected-outside-limit gates in 33.27 seconds.
- The document workspace test renders all six fields, verifies persisted exact selections, rejects a
  foreign tenant embedding ID, and proves embedding/OCR/model host and secret references are absent.
- `vitest run src/__tests__/scenario_manifest.test.tsx`: 7 passed, including exact staged-index deep
  linking and bounded published-version notification evidence.
- TypeScript `tsc --noEmit`, Vite production build (185 modules), Python Ruff format/check, mypy for
  `apps/console/views.py`, selector-script syntax, Django `manage.py check`, and `git diff --check`
  passed.
- A repeated full document-workspace run later stalled without output and was not counted as pass;
  no lingering pytest process or unhealthy Compose service remained, and the exact changed test then
  passed independently.

## Part 2B live/runtime evidence

- Canonical Compose state showed PostgreSQL, Redis, MinIO, web and all worker/beat roles running;
  `/v1/health/live` returned HTTP 200.
- The live document-set page loaded successfully with two scenario bindings and its active index.
  The open `admin` session did not have exact document-set manager responsibility, so the build form
  correctly remained hidden; no responsibility was broadened merely to make the browser check pass.

## Part 2B security/authorization evidence

- Artifact previews are escaped text and capped at 32 KiB; selector projections are capped at 100
  tenant-scoped choices per field. Users without exact document-set manager responsibility neither
  receive the inspectors nor trigger the artifact-body/profile-detail projection queries.
- Referenced model profiles are resolved in one bounded query and expose only logical ID, revision,
  provider, model and output-token bound. Embedding/OCR projections likewise omit endpoint, path,
  secret, TLS and network configuration.
- The cross-tab notification accepts only chunking/retrieval/prompt artifact messages with positive
  exact IDs/versions, bounded logical IDs and a serializable body no larger than 32 KiB. It changes
  only client selection state; the existing build POST remains the authorization authority.

## Part 2B residual items

- Closed creation of new tenant `model_profile` reference artifacts remains Part 2 work; existing
  model reference artifacts are inspectable but read-only from the staged-index page.
- The broader registry capability matrix and retrieval `metadata_filter` builder remain unfinished.
- Live browser interaction with the authorized manager-only form was not available in the existing
  session; automated PostgreSQL/Django and frontend evidence covers that path.

## Part 2C automated evidence

- `pytest apps/builder/tests/test_services.py apps/builder/tests/test_api.py -q`: 77 passed.
- The model-profile option/draft and inactive-source-copy tests prove active-profile enforcement,
  UUID-only bodies, exact scenario-author scope and safe-field redaction.
- Console artifact capability, scenario-author read/reuse, release-preset denial and builder
  bootstrap suites: 23 passed across the three affected test files.
- Focused frontend profile/draft/manifest run: 12 passed across 3 files; TypeScript typecheck and
  Vite production build passed with 187 modules transformed.
- Python Ruff format/check, mypy for the changed builder/console modules,
  `makemigrations --check --dry-run builder`, Django system check, selector-script syntax and final
  whitespace/diff checks passed.
- Additive migration `builder.0008_artifactdraft_model_profile` was applied to the local PostgreSQL
  database and confirmed by `showmigrations`.

## Part 2C live/runtime evidence

- The authorized live Studio session displayed **Yeni profil artifact'i** and active model-profile
  choices using only logical ID/revision, provider, model and output-token bounds.
- Selecting a profile displayed the safe summary, stated that endpoint/secret values are absent and
  kept creation disabled until the required logical metadata was supplied. No live draft or
  immutable version was created during acceptance.
- Existing model-profile artifact content opened in the inline exact-version editor. The controlled
  Compose web restart completed and `/v1/health/live` returned HTTP 200.

## Part 2C security/authorization evidence

- Exact scenario authors may inspect and version supported artifacts, but minimum preset, preflight
  and compile continue to use the exact release-manager authorization path. Tests cover the split.
- Model-profile bodies are revalidated as exactly `{profile_id: UUID}` on create, update, source
  copy and publish; the referenced platform profile must still be active at publication time.
- The tenant projection never serializes endpoint, host, path, secret reference, TLS, network or
  egress configuration. Foreign scenario/profile inputs fail through bounded, non-disclosing paths.
- Every registry type now receives a structured, guided-elsewhere or explicit read-only capability
  state; unsupported authoring is not presented as a working control.

## Part 2C residual items

- The platform model-profile catalog is intentionally platform-global because this repository has
  no tenant model-profile grant model; tenant artifacts can only reference active profile UUIDs.
- Existing retrieval `metadata_filter` values are preserved but remain read-only until a bounded,
  typed filter builder is designed and approved.
- Live acceptance used an administrator session; exact author-only separation is covered by backend
  and frontend tests rather than a second live identity.
