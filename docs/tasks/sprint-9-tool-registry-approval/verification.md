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

## Increment C — durable approval lifecycle + idempotent resume (no live egress)

Scope: additive `ToolInvocation` / `ApprovalRequest` models; the `request_tool_invocation`
/ `decide_approval` / `execute_invocation` / `cancel_invocation` services with
separation-of-duties, request-checksum binding, 30-minute approval expiry, idempotent
resume, uncertain-outcome handling, and redacted fail-closed audit. The default adapter
still performs no network I/O; no public surface or workflow node is wired yet.

### Commands and results

| Command | Result |
| --- | --- |
| `ruff format --check .` / `ruff check .` | Pass — 200 files |
| `mypy .` | Pass — no issues in 200 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes |
| `pytest` (SQLite, `config.settings.test`) | Pass — 245 passed, 2 skipped |
| `pytest --create-db` (PostgreSQL/pgvector, MCP+metrics enabled) | Pass — 247 passed |

New migration: `apps/tools/migrations/0002_toolinvocation_approvalrequest_and_more.py`
(additive — `ToolInvocation`, `ApprovalRequest`, per-consumer idempotency unique
constraint, org/status indexes). Applied cleanly on SQLite and PostgreSQL.

### Acceptance-criteria evidence (this increment)

- A high-risk side-effecting tool cannot execute before a valid authorized approval;
  low/medium tools auto-approve — `test_high_risk_requires_approval_then_resumes`,
  `test_low_risk_auto_approves_and_executes`.
- Separation of duties + authorization: the requester cannot self-approve; a non-approver
  role is denied; a decision is tenant-scoped — `test_self_approval_is_forbidden`,
  `test_unauthorized_approver_is_denied`, `test_cross_tenant_decision_is_not_found`.
- Time-bounding: an expired approval is denied and the invocation expires —
  `test_expired_approval_is_denied_and_invocation_expires`.
- Input-swap-after-approval is denied via the request-checksum binding —
  `test_input_swap_after_approval_is_denied`.
- Idempotency + never-double-execute: duplicate requests coalesce/conflict; a terminal
  invocation is not re-run; an uncertain outcome is recorded and never retried —
  `test_idempotent_request_and_conflict`, `test_execute_is_idempotent_and_never_
  reexecutes`, `test_uncertain_outcome_is_recorded_and_not_retried`.
- Rejected/cancelled invocations do not execute — `test_rejected_invocation_does_not_
  execute`, `test_cancel_pending_invocation`.
- Fail-closed audit persists: terminal-state writes and deny audits are committed inside
  the atomic block and the error is raised afterward, so a denial/terminal outcome is
  never rolled back by the raising path.

### Residual risk / not yet delivered

- The resume path holds the invocation row lock while calling the (currently no-egress)
  adapter; the real HTTP/MCP adapter must release the lock during the network call and
  record the outcome in a follow-up transaction. Noted for the real-adapter increment.
- `execute_invocation` requires the raw `tool_input` from the caller (never persisted;
  only a redacted copy is stored), modelling a short-lived payload; a durable
  encrypted-payload design for cross-restart resume remains separately approved future
  work (consistent with the Sprint 8 redaction stance).
- No public surface (console/API/MCP) or workflow `tool` node yet (increment D); the
  default adapter performs no live egress.

## Increment D1 — real HTTPS egress adapter (opt-in, default off)

Scope: `HttpToolAdapter` (stdlib `http.client`/`ssl`/`socket`, **no new dependency**)
selected by `TOOL_ADAPTER=http`; default remains the deterministic no-egress adapter.
The project owner explicitly approved end-to-end egress for Increment D.

### Commands and results

| Command | Result |
| --- | --- |
| `ruff format --check .` / `ruff check .` | Pass — 202 files |
| `mypy .` | Pass — no issues in 202 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes (no model) |
| `pytest` (SQLite) | Pass — 255 passed, 2 skipped |
| `pytest --create-db` (PostgreSQL/pgvector, MCP+metrics) | Pass — 257 passed |

### Security properties (evidenced in `test_http_adapter.py`, fully offline)

- Connects to the **already-validated public IP** while sending SNI/Host and verifying
  the TLS certificate for the **original hostname** — closes the DNS-rebinding TOCTOU
  window (`test_success_connects_to_validated_ip_and_sends_host_and_auth`).
- Redirects are never followed (`REDIRECT_NOT_ALLOWED`); non-2xx is an error; the body
  is read under a hard byte cap (`RESPONSE_TOO_LARGE`); non-JSON / non-object bodies are
  rejected; a credential becomes an ephemeral `Authorization` header (omitted when
  absent) and is never logged.
- A timeout after dispatch maps to `ToolAdapterUncertain` → `outcome_unknown` (never a
  false success); a pre-send connection error is a plain failure.

### Residual risk / not yet delivered

- Real egress is opt-in and unconfigured in CI/tests, which use the deterministic
  adapter; no live outbound call is made by the automated suite.
- The MCP egress adapter (protocol `mcp`) is not yet implemented — `HttpToolAdapter`
  rejects it with `PROTOCOL_UNSUPPORTED`. Public approval surfaces (REST/MCP), the
  workflow `tool` node with pause/resume, console views, and metrics remain (D2–D4).

## Increment D-surface — operator commands + bounded metrics

Scope: management commands `decide_tool_approval` / `list_tool_approvals` /
`cancel_tool_invocation` (role-resolved authorization) and bounded Prometheus counters
`agenthub_tool_invocations_total{status}` and `agenthub_tool_approvals_total{decision}`
wired via `post_save` signals (no coupling from the service layer).

### Commands and results

| Command | Result |
| --- | --- |
| `ruff format --check .` / `ruff check .` | Pass — 209 files |
| `mypy .` | Pass — no issues in 209 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes |
| `pytest` (SQLite) | Pass — 261 passed, 2 skipped |
| `pytest --create-db` (PostgreSQL/pgvector, MCP+metrics) | Pass — 263 passed |

### Acceptance-criteria evidence

- `decide_tool_approval` approves only for an authorized approver role and rejects a
  non-approver or unknown actor — `test_commands.py::test_decide_command_approves_for_
  approver`, `test_decide_command_denied_for_non_approver`, `test_decide_command_unknown_
  actor`.
- `list_tool_approvals` shows pending requests for an org; `cancel_tool_invocation`
  cancels tenant-scoped — `test_list_command_shows_pending`, `test_cancel_command_
  cancels_invocation`.
- Metrics stay bounded and are emitted from DB signals — `test_approval_decision_
  increments_bounded_metric`.

## Increment D-final — MCP egress, workflow tool node + pause/resume, console

Scope: the MCP egress adapter; the workflow `tool` node with durable pause/resume; the
operator console approval view; and auto-resume on decision. Completes Sprint 9.

### Commands and results

| Command | Result |
| --- | --- |
| `ruff format --check .` / `ruff check .` | Pass — 214 files |
| `mypy .` | Pass — no issues in 214 source files |
| `python manage.py makemigrations --check --dry-run` | Pass — no changes |
| `pytest` (SQLite) | Pass — 275 passed, 2 skipped |
| `pytest --create-db` (PostgreSQL/pgvector, MCP+metrics) | Pass — 277 passed |

New migration: `apps/workflows/migrations/0002_workflowrun_awaiting_node_alter_workflowrun_status.py`
(additive — `awaiting_node` checkpoint field + `waiting_approval` status). Applied cleanly
on both databases.

### Acceptance-criteria evidence

- MCP egress: a bounded JSON-RPC `tools/call` over the same SSRF-safe pinned-IP/TLS
  transport; JSON-RPC/tool errors and malformed results are rejected — `test_mcp_adapter.py`.
  `get_configured_adapter` dispatches http/mcp by protocol when `TOOL_ADAPTER` enables egress.
- Workflow tool node: a high-risk tool pauses the run (`waiting_approval` + durable
  `awaiting_node` checkpoint), an operator decision resumes it to completion, a rejection
  fails the run closed, and a low-risk tool completes without a pause —
  `test_tool_node.py`. Auto-resume is wired via a post-commit signal on the decision.
- Console approval view: role-gated approve/reject/cancel, tenant-scoped, POST-only for
  decisions, graceful denial — `test_tool_approval_views.py`.

### Residual risk

- On resume the tool executes with the run's redacted checkpoint state (deterministic
  governance runtime); a durable encrypted/short-lived raw-payload design for tools that
  need confidential raw text across a restart remains separately approved future work
  (consistent with the Sprint 8 redaction stance).
- The real HTTP/MCP adapters hold no DB lock during egress in the standalone proxy, but
  the workflow resume path executes the tool inside the run's transaction; moving the
  network call outside the row lock is a hardening follow-up for high-latency tools.
- Real OTel/Prometheus/live-egress validation remains an operational follow-up; the
  automated suite uses the deterministic no-egress adapter.
