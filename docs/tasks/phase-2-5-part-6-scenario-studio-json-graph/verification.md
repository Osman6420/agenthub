# Verification: Scenario Studio JSON and graph authoring completion

## Acceptance evidence

- Server bootstrap locks and labels scenario/project/organization context and exposes an active
  workflow source only when its exact immutable artifact checksum matches the active release pin.
- New scenario drafts accept either an empty graph start or a complete non-empty workflow body. A
  non-empty body is rejected before persistence unless canonical workflow diagnostics pass.
- Open drafts provide graph and JSON views over one candidate body. JSON must pass the backend
  diagnostics endpoint before replacing graph state; unapplied JSON disables save/publish actions
  and participates in the browser unload warning.
- Existing scenario drafts open automatically. A scenario with only an active workflow can preview
  that exact body read-only as JSON/graph or explicitly copy it to a new scenario-linked draft.
- AI candidate acceptance carries locked project and scenario lineage.

## Automated verification

| Check | Result |
| --- | --- |
| Frontend Vitest | 19 passed |
| Frontend TypeScript/Vite build | Passed; 204 modules transformed |
| Focused builder + scenario backend | 66 passed |
| Full SQLite | 694 passed, 29 PostgreSQL-only skipped in 32.11s |
| Full PostgreSQL/RLS/pgvector | 718 passed, 5 SQLite-only skipped in 367.22s |
| Ruff | Passed |
| mypy | 358 source files clean |
| Django system check | No issues |
| Migration drift | No changes detected |
| compileall | Passed |
| `git diff --check` | Passed |

The first full SQLite attempt completed 693 tests and then hit the known inaccessible Windows user
Temp cleanup path. Re-running the unchanged suite with workspace `--basetemp` passed; no assertion,
test or control was weakened. The canonical Compose image also reproduced its documented Dockerfile
copy-order defect before tests; verification used the repository venv against healthy local
PostgreSQL instead.

## Final reviews

- Staff engineer: JSON and graph reuse the existing workflow body/compiler; immutable artifacts and
  releases are not edited and no second schema was introduced.
- Application security: scenario scope is resolved server-side, imported bodies are bounded and
  validated before persistence, active bodies require checksum equality, and AI lineage no longer
  drops the scenario ID.
- SRE: no dependency, migration, runtime activation or new external call was added; failures remain
  stable authoring errors and the full SQLite/PostgreSQL suites pass.

## Manual evidence pending

Authenticated Turkish owner checks 2.21–2.25 remain pending, including complex graph usability and
visual confirmation that each scenario remains isolated on its own Studio page.
