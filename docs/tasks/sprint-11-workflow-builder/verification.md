# Verification: sprint-11-workflow-builder

Sprint 11 delivers the governed workflow builder: a tenant-scoped draft API + compiler
diagnostics + node-schema generation + a shared-path publish (`apps.builder`), and a React
Flow SPA (`frontend/`) served same-origin through Django. The frontend is non-authoritative;
the workflow DSL and backend services are the source of truth.

## Environment

- Interpreter: `.venv` (Python 3.13), dependencies from `requirements.lock`.
- Node toolchain: Node v20.20.0 / npm 10.8.2 (build-time only; the SPA ships as static
  assets). Frontend dependencies pinned in `frontend/package-lock.json`.
- SQLite gates: `DJANGO_SETTINGS_MODULE=config.settings.test`.
- PostgreSQL gates: `DJANGO_SETTINGS_MODULE=config.settings.local` with `--create-db`,
  `MCP_ENABLED=true`, `METRICS_BEARER_TOKEN` set, and a writable `--basetemp` on Windows.

## Commands and results

### Backend increment (implemented and verified)

| Command | Result |
| --- | --- |
| `ruff format --check .` | Pass — 252 files |
| `ruff check .` | Pass — all checks passed |
| `mypy .` | Pass — no issues in 252 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes detected |
| `python manage.py check` | Pass — no issues (0 silenced) |
| `pytest` (SQLite, `config.settings.test`) | Pass — 364 passed, 2 skipped (+27 builder) |
| `pytest apps/builder apps/console --create-db` (PostgreSQL) | Pass — 46 passed |

New additive migration `apps/builder/migrations/0001_initial.py` (`WorkflowDraft`,
unique `(organization, logical_id)`, `(organization, -updated_at)` index). Applied cleanly
on SQLite and PostgreSQL. 27 builder tests in `apps/builder/tests/`.

### Frontend increment (React Flow SPA)

Interpreter: Node v20.20.0 / npm 10.8.2. Dependencies pinned in
`frontend/package-lock.json` (React 18.3.1, React DOM 18.3.1, `@xyflow/react` 12.3.5,
Vite 5.4.8, TypeScript 5.6.2, Vitest 2.1.2). Build output → `apps/builder/static/builder/`
(gitignored; regenerate with `npm --prefix frontend run build`).

| Command | Result |
| --- | --- |
| `npm ci` (frontend) | Pass — 204 packages, lockfile consistent |
| `npm run typecheck` (`tsc --noEmit`, strict) | Pass — no errors |
| `npm test` (vitest: unit + e2e builder flow) | Pass — 3 files, 11 tests |
| `npm run build` (`tsc --noEmit && vite build`) | Pass — `builder.js` 329.7 kB / 106.4 kB gz, `builder.css` |
| `manage.py findstatic builder/builder.js builder/builder.css` | Pass — resolved from `apps/builder/static/builder/` |

Frontend tests: `dsl.test.ts` (deterministic serialization, node/edge sorting, empty-config
omission, typed `when` edges, round-trip stability, malformed-body safety),
`schema.test.ts` (enum option resolution, default config, unique id suggestion),
`flow.test.tsx` (**end-to-end builder flow** through the real API client with mocked fetch:
build graph from palette → validate → save → publish, CSRF header asserted, dirty→saved
transition; plus read-only mode blocks edits and issues no write).

## Acceptance-criteria evidence

- **Builder creates a versioned DSL, not a runtime graph.** The SPA serializes the canvas
  to a workflow DSL body (`dsl.ts`), never a compiled graph; `WorkflowDraft` stores that
  body; publish creates an immutable `workflow_definition` `ArtifactVersion`
  (`test_api.py::test_publish_creates_workflow_artifact`,
  `test_services.py::test_publish_is_immutable_source_of_truth`). Node positions/layout are
  excluded from the DSL.
- **Publish uses the same compiler/eval/promotion path.** `publish_draft` routes through
  `create_artifact_version` (shared `validate_body` = inline-secret rejection + workflow
  compiler) with no bypass; releasing/eval/promotion remain the existing release-manager
  flow. `test_publish_rejects_inline_secret`, `test_diagnose_matches_publish_on_secret`.
- **UI never shows tool endpoints or secret values.** `build_node_schema` returns only
  binding *role* names + approval flag and public config schema;
  `test_node_schema_exposes_roles_never_endpoints_or_secrets` asserts the tool endpoint and
  `secret:` reference never appear; `test_node_schema_excludes_other_tenant_bindings`.
- **Reuses LDAP identity + role/tenant authorization; no separate path.** The API is
  session/LDAP authenticated with `allowed_organization_ids` read scope and
  `can_author_scenarios` write gate; unauthenticated → 401, wrong-role → 403, cross-tenant
  → 404, CSRF enforced (`test_api.py`). The SPA is served same-origin by Django with no CORS
  and no token path; the client `can_write` flag only mirrors the server decision.
- **Owner-specified minimum features.** Draft create/edit/save (`App.tsx`, `useBuilder`),
  node palette + drag/drop canvas (`Palette`, `Editor` `onDrop`), typed edge connections
  (`Editor` condition-branch `when` typing + `isValidConnection`), node config panel
  (`NodeConfigPanel`, schema-generated), backend compile/validation errors displayed on the
  graph (`useBuilder.applyErrorHighlights` + `Toolbar` banner + node red border),
  unsaved-change protection (`Editor` `beforeunload` + dirty flag), read-only mode by role
  (`readOnly` gates every mutating action), deterministic DSL serialization
  (`dsl.ts` canonical + sorted output, proven byte-identical), unit tests + one e2e flow.

## Security / privacy notes

- The builder grants no capability GitOps does not: every publish re-validates via the
  shared `create_artifact_version` (schema + inline-secret rejection + checksum).
- The frontend is non-authoritative. All validation, authorization, lifecycle, and
  publishing happen server-side; the client renders backend diagnostics/state only.
- Tool endpoints, tool-definition manifests, and `secret:<name>` references never leave the
  backend — the node-schema projection excludes them by construction.
- Draft bodies are bounded (256 KiB) and never logged; state changes are audited
  (`console.builder.draft.create/update/delete/publish`), publish recording the artifact
  checksum.
- The React Flow SPA adds a build-time-only supply chain (pinned lockfile, MIT deps);
  `npm ci` + a Node CI job fail closed on lockfile drift. No runtime Python dependency added.

## Residual risk / not delivered

- No headless-browser/live-server smoke was run; the frontend is verified by vitest
  (jsdom) + the build, and Django static resolution by `findstatic`. A running local
  Uvicorn (if any) must be restarted and the bundle built before serving the builder page.
- The built bundle is gitignored (generated artifact); deploy/CI must run
  `npm --prefix frontend run build` before `collectstatic`. The Python runtime and gates do
  not depend on the bundle existing (the console page degrades gracefully).
- Switching drafts in the SPA relies on `beforeunload` for unsaved protection; in-app
  navigation away from a dirty editor is not additionally guarded in this increment.
- An authorized scenario editor can still author a semantically weak but schema-valid
  workflow — caught by the existing eval/promotion gate, unchanged from GitOps.
