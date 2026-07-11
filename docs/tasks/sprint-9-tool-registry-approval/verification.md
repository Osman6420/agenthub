# Verification: sprint-9-tool-registry-approval

Sprint 9 is being delivered in verified, independently committable increments. This
record is appended per increment.

## Increment A — tool registry data foundation (no egress)

Scope: `tool_definition` / `tool_binding` artifact validation, the tenant-scoped
immutable `ToolDefinition` / `ToolBinding` registry models, registration services with
the high-risk approval invariant, and fail-closed release pinning of active bindings.
No execution proxy, outbound network path, secret resolution, or approval lifecycle is
introduced in this increment — the platform still performs **no tool egress**.

### Environment

- Interpreter: `.venv` (Python 3.13), dependencies from `requirements.lock`. No new
  production dependency was added.
- SQLite gates: `DJANGO_SETTINGS_MODULE=config.settings.test` (in-memory).
- PostgreSQL/pgvector gates: `DJANGO_SETTINGS_MODULE=config.settings.local` against the
  Docker Compose `pgvector/pgvector:pg16` database, run with `pytest --create-db` and
  `MCP_ENABLED=true` / `METRICS_BEARER_TOKEN` set so the Sprint 7 MCP/metrics tests
  (which `config.settings.test` hard-codes) also run under `local` settings.

### Commands and results

| Command | Result |
| --- | --- |
| `ruff format --check .` | Pass — 192 files |
| `ruff check .` | Pass — all checks passed |
| `mypy .` | Pass — no issues in 192 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes detected |
| `python manage.py check` | Pass — no issues |
| `pytest` (SQLite, `config.settings.test`) | Pass — 202 passed, 2 skipped (PostgreSQL-only) |
| `pytest --create-db` (real PostgreSQL/pgvector) | Pass — 204 passed |

New migration: `apps/tools/migrations/0001_initial.py` (additive — `ToolDefinition`,
`ToolBinding`, per-org/logical/version unique constraints). No destructive change;
applied cleanly on SQLite and PostgreSQL via `--create-db`.

### Acceptance-criteria evidence (this increment)

- Tool artifacts are validated as bounded, allowlisted data — `test_tool_artifacts.py`
  (valid definition/binding pass; IP/private/`.internal`/`localhost` hosts, non-https
  scheme, unknown protocol, `critical` risk, out-of-range limits, literal `secret_ref`,
  malformed refs, unknown fields, mcp-with-method, http-without-method all rejected).
- Default-deny registry: a definition registers only for an organization in its own
  allowlist; a binding resolves its definition tenant-scoped — `test_tool_registry.py::
  test_register_definition_requires_org_allowlist`, `test_register_binding_missing_
  definition_is_denied`, `test_binding_cross_tenant_definition_is_denied`.
- Fail-closed high-risk policy: a high-risk side-effecting tool cannot bind without
  required approval and no self-approval — `test_high_risk_side_effecting_tool_requires_
  approval`, `test_high_risk_binding_with_valid_approval_registers`.
- Release pinning is fail-closed: only a registered, active, checksum-matching binding
  (with an active definition) pins into the manifest — `test_compile_release_pins_
  registered_binding`, `test_compile_release_fails_when_binding_not_registered`,
  `test_compile_release_fails_when_definition_disabled`.
- Registry immutability: a definition/binding body is write-once; only `status` may
  flip — `test_definition_body_is_immutable_but_status_can_change`.

### Residual risk / not yet delivered

- No execution proxy, HTTP/MCP adapter, DNS/redirect/SSRF egress enforcement, secret
  resolution, approval lifecycle, or durable resume exists yet (increments B–D). The
  destination allowlist in a definition is validated for shape only; post-DNS and
  redirect checks are the proxy's responsibility and are not present.
- Bindings must be explicitly registered by a platform/registry service before a release
  can pin them; console/API registration surfaces arrive in a later increment.

## Increment B — tool execution proxy (policy + egress seam, no live egress)

Scope: the central default-deny `invoke_tool` proxy, SSRF-safe destination validation,
the transport-adapter and secret-resolver seams, and `resolve_release_tool` (reads the
release-pinned binding/definition/contracts). No production dependency was added; the
default adapter performs **no network I/O**, and the proxy is **not yet wired** into any
workflow node or gateway path, so no live tool egress exists. Public behavior unchanged.

### Commands and results

| Command | Result |
| --- | --- |
| `ruff format --check .` / `ruff check .` | Pass — 198 files |
| `mypy .` | Pass — no issues in 198 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes (no new model) |
| `pytest` (SQLite, `config.settings.test`) | Pass — 232 passed, 2 skipped |
| `pytest --create-db` (PostgreSQL/pgvector, MCP+metrics enabled) | Pass — 234 passed |

### Acceptance-criteria evidence (this increment)

- SSRF/egress: only public unicast destinations pass; loopback, private, link-local,
  unspecified, IPv6 ULA/link-local, and any public+private mix (DNS-rebinding) are
  denied; non-https scheme, IP-literal host, bad port, empty/failed DNS are denied —
  `test_egress.py` (validated through an injected resolver, deterministic offline).
- Default-deny policy: capability gate (read vs side-effecting), input/output contract
  validation, input/output field allowlists (mass-assignment + exfiltration defense),
  and bounded response size — `test_proxy.py`.
- A high-risk side-effecting tool is never executed — `test_approval_required_raises_
  and_never_executes` asserts `ToolApprovalRequired` is raised and the adapter is not
  called.
- Least-privilege secrets: a missing secret fails closed; a resolved credential is
  passed to the adapter but never appears in the returned result — `test_missing_secret_
  fails_closed`, `test_secret_is_passed_to_adapter_but_not_returned`.
- Release-pinned resolution: `resolve_release_tool` reads the pinned binding/definition
  (checksum-matched) and contracts and feeds `invoke_tool`; an unpinned role fails
  closed — `test_resolve_release_tool_then_invoke`, `test_resolve_release_tool_missing_
  role_fails_closed`.

### Residual risk / not yet delivered

- The real HTTP/MCP adapter (TLS verification, disabled redirects, bounded streaming
  read against the validated IP) is not implemented; the default adapter is a no-egress
  stub and requires explicit approval plus any client dependency before real egress.
- No durable invocation record, idempotency, approval lifecycle, or workflow
  pause/resume yet (increment C); the proxy has no production caller yet.
