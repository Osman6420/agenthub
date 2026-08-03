# Verification: scenario-studio-authoring-journey-closure-part-1

## Baseline

- 2026-08-03: parent plan committed at `787d1e5`.
- Active branch: `feat/foundation-sprint-0-1`.
- Working tree before Part 1 contained only unrelated untracked `agenthub-openshift.tar.gz`; preserve
  and exclude it.
- Codebase Memory project `C-Users-kuzuc-Desktop-agenthub` was available. Artifact architecture shows
  canonical `create_artifact_version` as the principal write hotspot. Serena tools were unavailable;
  exact source/test inspection and `rg` are the fallback authority.
- No active agent handoff and no live runtime state assumed.

## Commands and evidence

- Changed Python files: Ruff format check and Ruff security/lint check passed.
- Repository Ruff format check found one unrelated pre-existing formatting delta in
  `apps/retrieval/providers.py`; Part 1 did not modify that file.
- `python -m mypy apps`: passed, 448 source files.
- `manage.py makemigrations --check --dry-run`: no changes detected.
- `manage.py check`: no issues; `compileall -q apps config`: passed.
- Full backend suite with `config.settings.test`: 1,141 passed, 61 PostgreSQL/environment skips.
- Focused PostgreSQL suite with `config.settings.local`: 72 passed across artifacts and builder
  API/services. This exercised the additive migration, tenant queries, row locking, publication,
  authorization, and immutable-version paths against PostgreSQL.
- Final focused builder suite after adding audit-failure rollback coverage: 65 passed.
- Final PostgreSQL audit-failure rollback test with the retained test database: 1 passed.
- Full frontend Vitest suite: 9 files, 37 tests passed. TypeScript `tsc --noEmit` passed.
- Production frontend build passed: 183 modules; generated bundle remained gitignored.
- Targeted changed-lines secret-pattern scan passed. No production dependency or lockfile changed.
- `git diff --check`: passed.
- Additive migration `builder.0006_artifactdraft_prompt_publication` was applied successfully to the
  local development database; Django reports no missing model migrations.

## Browser gate

- Live Compose topology and `/v1/health/live` were inspected before testing; web, PostgreSQL, Redis,
  MinIO, and workers were available and health returned HTTP 200.
- An authorized scenario author opened exact prompt v1 in the manifest picker, saw the bounded body,
  created a new-version draft, edited the prompt, and published immutable v2/v3. The original v1 body
  remained visible and unchanged.
- Clicking publish with an empty exact-version note produced the announced Turkish error, focused the
  note input, and did not publish.
- Returning from publication refreshed artifact type, logical ID, version history, and selected the
  newly published exact version without a page reload.
- The author also created a new logical prompt entirely in Studio and published its immutable v1.
- A viewer saw prompt drafts as disabled read-only content and had no create/save/delete/publish or
  candidate-manifest controls. A cross-tenant user received the non-disclosing console 404 at the
  exact Studio URL.
- Browser console error log was empty after the completed journeys.
- The first preview attempt hit the old URL table in the already-running web process; a controlled
  web restart loaded the additive route and health returned 200 before the successful rerun.
- Exact synthetic records (`codex-part1-*`) were verified and removed after testing; zero synthetic
  organizations/users remain.

## Final review

- Staff engineering: publication reuses the canonical validator/checksum/immutable service; the
  additive draft schema preserves existing input/output behavior. Tenant-row locking serializes rare
  control-plane version allocation and avoids duplicate N+1 races.
- Application security: server-side scenario/tenant authorization and CSRF remain authoritative;
  foreign IDs are non-disclosing, previews are bounded and React-escaped, inline-secret validation is
  fail-closed, and prompt bodies are excluded from audit metadata. Audit failure rolls back both the
  artifact and draft publication state.
- SRE: no new service, worker, egress, dependency, or public runtime contract was introduced. The
  migration is additive. Per-tenant serialization is an accepted low-volume control-plane tradeoff.
- Residual scope: Part 1 delivers prompt-first selector inspection/versioning, not the parent plan's
  full artifact history/diff/usage workspace or retrieval/profile editors; those remain later parts.
