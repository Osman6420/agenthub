# Verification: P2.6.7 governed MCP catalog synchronization

## Result

Implemented but **activation-blocked** on `codex/p2-6-7-mcp-activation-closure` from `7f18a26`.
Quarantine, exact review, immutable registration, drift/disappearance, bounded metadata validation,
redacted audit and unchanged exact-pinned proxy behavior are verified. Production application-role
authorization is not changed without approval, so the RLS provisioning gate remains intentionally
red.

## Automated evidence

All Python checks used the manual guide's disposable Python 3.13 container fallback because the
Microsoft Store-backed `.venv` launcher failed before Python start with `A specified logon session
does not exist`. No live external MCP system was contacted.

| Check | Result |
| --- | --- |
| Branch/base | `codex/p2-6-7-mcp-activation-closure` at `7f18a268bbde5ca4fa62b503d4c33bf79b94d9c8` |
| Compose readiness | PostgreSQL, Redis and MinIO reported healthy |
| Focused SQLite catalog/egress/MCP/proxy | **51 passed** |
| Full SQLite regression | **881 passed, 33 skipped, 1 failed**; sole failure is the named production app-role blocker below |
| Focused PostgreSQL catalog/RLS | **14 passed, 2 skipped, 1 failed**; sole failure is the same provisioning blocker |
| Ruff format/check (`apps config`) | **Passed**; 395 files formatted, lint clean |
| mypy | **Passed**; no issues in 385 source files |
| Django system check | **Passed**; no issues |
| Migration drift | **Passed**; `No changes detected` |
| `git diff --check` | **Passed** |

Focused tests prove discovery creates no artifact/definition/binding, secrets/endpoints are absent
from audit, tenant mismatches are hidden, malicious names and catalog explosion deny, mixed
public/private DNS denies, the JSON-RPC request is bounded `tools/list`, stale review denies, exact
review creates only an immutable definition, and changed/disappearing tools remain non-authoritative.
Existing redirect denial and exact release-pinned proxy suites pass in the same run.

## Blocking gate

`apps/tenancy/tests/test_rls_readiness.py::test_provisioning_sql_names_every_protected_table` reports
`tools_mcpcatalogsource` and `tools_mcpcatalogcandidate` missing from
`deploy/postgres/provision-app-role.sql`. The additive migration installs and forces tenant policies,
but changing that production grant inventory is an authorization change requiring explicit approval.
No bypass, weakened test or unapproved SQL change was made. Unblock by approving the scoped addition
of both tables to the protected SELECT/INSERT/UPDATE grant lists, then run the non-owner PostgreSQL
cross-tenant proof and both full profiles.

## Checks not run

- Full PostgreSQL regression and non-owner catalog-table cross-tenant access: blocked by the missing
  approved production app-role grants.
- Live MCP server, production CA/DNS/firewall/credential, redirect service and live egress: prohibited
  by task scope; deterministic fixtures and existing redirect transport tests were used.
- Tenant UI/browser review: no UI or public API was added.

## Final review

- **Staff engineer:** implementation is local to `apps.tools`; registry/artifact/proxy seams are
  reused, runtime pins are unchanged, and discovery cannot create bindings/releases/grants.
- **Application security:** tenant scoping, DNS/IP pinning, redirect-free transport, secret lifetime,
  schema/name/count/depth/byte bounds, exact review and redacted atomic audit were reviewed. The
  unapproved production grant is correctly fail-closed.
- **SRE:** additive migration has reversible FORCE RLS setup, no dependency/config/network change,
  and deterministic failure codes. Production rollout is blocked until grants and non-owner proof
  pass; rollback is migration reversal plus source disable, while existing pins remain immutable.
