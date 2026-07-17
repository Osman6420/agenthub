# Verification: Phase 2.6 activation-closure wave integration gate

## Result

Verified on `codex/p2-6-activation-integration` on 2026-07-17 and landed on
`feat/foundation-sprint-0-1`. The merged P2.6.7 MCP activation closure, P2.6.8 OpenShift
fixed-pool runner, P2.6.9 Studio AI activation and P2.6.10 ingestion activation-closure branches
pass the static, full SQLite, full PostgreSQL and frontend gates on the merged tree. The owner
approved the P2.6.7 catalog-table application-role grant inventory at this gate, closing the one
intentionally red check that P2.6.7 had recorded. Production activation remains gated: live MCP
endpoints/credentials are deployment-gated, `PYTHON_NODE_RUNNER_ATTESTED` is never set in-repo
(ADR-0011 target attestation outstanding), and no release/runtime default changed.

## Merge integrity

- Wave base `7f18a268` (`docs(phase-2-6): plan activation closure wave`); integration head at gate
  start `93a9997` with first-parent merges `16958f0` (P2.6.7), `203b3d1` (P2.6.8+P2.6.9, the
  P2.6.9 branch having first merged the P2.6.8 runner contract at `fdcaacf`) and `93a9997`
  (P2.6.10).
- All four activation branch tips (`42e90a3`, `e84e578`, `65b9455`, `25a7880`) are ancestors of the
  head; `git branch --merged` confirms no unmerged activation commit anywhere.
- Diffing each branch tip against the head over that branch's delivered paths is empty except one
  line in `config/settings/base.py`: P2.6.9's own `PYTHON_NODE_PUBLIC_CATALOG_PROVIDER` setting.
  No sibling implementation was dropped by the merges.

## Environment

- Repository `.venv` Python 3.13.14 (Windows 11); no container fallback was needed this session.
- Canonical Compose infrastructure queried live: `agenthub-postgres-1` (pgvector/pg16),
  `agenthub-redis-1` (redis:7) and `agenthub-minio-1` all healthy. No other session's process was
  stopped; this gate only created disposable test databases (`--create-db`) and ephemeral
  `NOSUPERUSER` probe roles.
- Frontend gates on the pinned `frontend/package-lock.json` via `npm ci` (Node toolchain per
  Sprint 11 contract).

## Approved authorization change (owner, 2026-07-17)

`tools_mcpcatalogsource` and `tools_mcpcatalogcandidate` were added to
`deploy/postgres/provision-app-role.sql`: the protected FORCE-RLS SELECT list and the
no-application-delete INSERT/UPDATE list. No DELETE was granted; both tables keep the
migration-installed FORCE RLS `tenant_isolation` policy. This is the scoped unblock that the
[P2.6.7 verification](../phase-2-6-part-7-mcp-catalog-sync/verification.md) prescribed; applying
the provisioning script to a live environment remains a rollout step.

## Automated evidence

| Check | Result |
| --- | --- |
| Ruff format / lint (repository) | Passed; 401 files formatted, lint clean |
| mypy (repository) | `Success: no issues found in 401 source files` |
| Django system check | No issues |
| Migration drift (`makemigrations --check --dry-run`) | `No changes detected` |
| `compileall apps config` / `git diff --check` | Passed |
| Full SQLite regression, first run | `1 failed, 893 passed, 33 skipped` — the sole failure was the known intentional P2.6.7 provisioning-inventory blocker |
| Full SQLite regression after approved grants | `894 passed, 33 skipped` |
| Full SQLite regression, final tree | `894 passed, 35 skipped` (2 new skips are the PostgreSQL-only catalog RLS proofs) |
| Full PostgreSQL regression (`config.settings.local`, fresh `--create-db`, MCP/metrics enabled) | `922 passed, 5 skipped` in 285s; fresh test database applied the complete merged migration graph including `tools.0003` |
| Non-owner catalog-table RLS proof (new `apps/tools/tests/test_catalog_rls.py` + tenancy readiness, PostgreSQL) | `9 passed, 2 skipped`; empty/wrong `app.tenant_scope` under a `NOSUPERUSER NOBYPASSRLS` role returns no rows on both catalog tables, correct scope returns them; FORCE RLS + `tenant_isolation` policy present |
| Frontend `npm ci` → `tsc --noEmit` → `vitest` → `vite build` | 204 packages; type-check clean; `20 passed (7 files)`; production bundle built to `apps/builder/static/builder/` |

The provisioning-inventory readiness test (`test_provisioning_sql_names_every_protected_table`)
now passes in both profiles, and the SQLite suite includes the P2.6.9 deferred full-regression gate
this wave owed.

## Checks not run

- Live MCP server, production CA/DNS/firewall/credential and any live egress: deployment-gated by
  the P2.6.7 record; deterministic fixtures only.
- Target OpenShift restricted-v2 admission, service-mesh mTLS, effective NetworkPolicy, image
  signature/SBOM and live recycle/resource/escape probes: the ADR-0011 production activation gate
  for P2.6.8; no cluster is available locally.
- Browser-driven Studio journey: deferred to P2.6.11 final Phase 2.6 acceptance (component tests
  and the production bundle cover the SPA seam).
- Live worker/broker outage drills were not repeated at this gate; the P2.6.10 record holds the
  real-service activation drills on the identical ingestion code.
- The provisioning script was not applied to a live non-owner role environment; readiness is proven
  with ephemeral in-database roles.

## Final review

- **Staff engineer:** the merges preserve each branch's delivered files (one legitimate shared
  settings addition); no compiler/runtime seam was redesigned during integration; the only code
  added at the gate is the PostgreSQL-only RLS proof test.
- **Application security:** the approved grant is least-privilege (no DELETE, FORCE RLS retained),
  the non-owner cross-tenant proof passes on both new tables, and no authentication, public API,
  secret or egress default changed at this gate.
- **SRE:** fresh PostgreSQL apply of the full merged migration graph passed; rollback for the grant
  is removing the two tables from the provisioning script (plus `tools.0003` reversal if ever
  required); production activation for MCP egress and the Python runner remains explicitly gated.

## Status

Activation-closure wave integration gate closed on 2026-07-17. `feat/foundation-sprint-0-1`
fast-forwards to the verified head. P2.6.6 is the next implementation part; P2.6.11 final
acceptance follows.
