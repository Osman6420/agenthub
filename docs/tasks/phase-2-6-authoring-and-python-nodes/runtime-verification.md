# Verification: P2.6.8 isolated-runtime integration

## OpenShift fixed-pool update (2026-07-17)

Implemented on `codex/p2-6-8-openshift-runner` from integration baseline `7f18a26`:

- four-replica internal runner Deployment, ClusterIP Service and PDB;
- dedicated tokenless ServiceAccount, no Secret/ConfigMap/volume, RuntimeDefault, non-root,
  read-only root, dropped capabilities and bounded resources;
- NetworkPolicy allowing only runtime-worker ingress, with runner excluded from DNS/general egress;
- minimal credentials-free runner image and stdlib supervisor, concurrency one, fresh process per
  call and supervisor recycle after 20 executions/15 minutes;
- bounded no-redirect application adapter that maps saturation and transport ambiguity to stable
  fail-closed outcomes;
- separate `PYTHON_NODE_RUNNER_ATTESTED` gate. Repository manifests never set it or activate Python
  execution.

Target OpenShift restricted-v2 admission, service-mesh mTLS, effective NetworkPolicy, image
signature/SBOM and live recycle/resource/escape probes are not available locally and remain the
production activation gate. The earlier evidence below remains the authority for the original
runtime seam.

| Fixed-pool check | Result |
| --- | --- |
| Focused runner/seam/manifest tests | `39 passed` |
| Full SQLite regression | `882 passed, 33 skipped` |
| PostgreSQL workflow/tenancy regression | `197 passed, 3 SQLite-only skipped` |
| Ruff lint and format | Passed; 399 files formatted |
| mypy | `Success: no issues found in 399 source files` |
| Django system check / migration drift | No issues / no changes detected |
| Canonical infrastructure | PostgreSQL, Redis and MinIO healthy via Compose |
| Minimal runner image | Built from digest-pinned `python:3.13-slim`; local image `agenthub-python-runner:p2-6-8` |

This record is intentionally separate from the first-wave isolation-spike verification. It records
commands and evidence for the runtime integration branch only.

## Safety posture

- Production activation: **disabled**.
- Implemented isolation: separate OS process test harness with parent-enforced deadline/output bounds,
  child-enforced POSIX memory limit when available, restricted builtins/imports and an empty environment.
- Not claimed: production sandbox, kernel isolation, seccomp/LSM, network namespace, container image,
  credentials boundary or OpenShift admission evidence.
- Dependencies: no production or development dependency added.

## Evidence

Verified on branch `phase-2-6/p2-6-8-isolated-runtime`, based directly on `c4d47b1`.

| Check | Result |
| --- | --- |
| Branch/base and clean isolation | Branch created by `git worktree add ... -b phase-2-6/p2-6-8-isolated-runtime c4d47b1`; no spike/parallel merge or rebase |
| Compose config/state | `docker compose ... config --quiet` passed; PostgreSQL, Redis and MinIO healthy; no web/worker runner inferred or started |
| Host focused seam tests | `23 passed` under host Python 3.14 with conftest/plugin isolation; used only as early pure-Python feedback |
| Canonical Python 3.13 focused tests | Disposable `python:3.13-slim`, unchanged `.[dev]`: `48 passed` covering Python-node, managed-node and compiler suites |
| Formatter | `ruff format --check .`: `387 files already formatted` |
| Ruff | `ruff check .`: passed |
| Type check | `mypy .`: success, no issues in 387 source files |
| Django system check | `python manage.py check`: no issues |
| Migration drift | `python manage.py makemigrations --check --dry-run`: no changes detected |
| Byte compilation | `python -m compileall -q apps config`: passed |

The repository `.venv` launcher failed before Python startup with the documented Windows
`A specified logon session does not exist` error. Per `docs/manual-testing-guide.md` section 0.1,
the canonical checks therefore ran in disposable Python 3.13 containers. Dependency installation
used the unchanged `pyproject.toml`; repository manifests/locks were not modified.

The first Linux memory probe used a 1 MB address-space limit, which killed the interpreter before
it could emit the bounded protocol and produced one expected test failure (`43 passed, 1 failed`).
The probe was corrected to preserve interpreter baseline while allocating 80 MB against a 64 MB
limit; the rerun passed. An early repository Ruff run also saw the agent-created `.pytest-isolated`
copy; that temporary directory was verified inside this worktree and removed before the clean full
gate run.

## Test coverage mapping

- Unapproved/rejected/disabled/stale, checksum/contract mismatch and cross-tenant lookup fail closed.
- Static review covers syntax, exact module requests, forbidden imports/calls, reflection and direct
  network/filesystem/process/environment-secret attempts without source excerpts.
- Config/input/output JSON Schema validation and P2.6.1 protected/copy-on-success state mapping run
  on both compile and runtime boundaries.
- Separate-process probes cover deadline, memory and output size; raw stderr is discarded.
- Active exact pins are resolved before dispatch and after return, covering disable/checksum races.
- Re-delivery with the same durable key is deterministic and side-effect free; workflow-run durable
  idempotency remains the existing outer authority.
- Audit assertions prove source, config/input values and exceptions are absent; persisted workflow
  events contain only node ID, stable outcome and stable reason code.
- Existing managed-node compile/execute tests pass unchanged.

## Final reviews

- **Staff engineer:** compiler shape is additive (`execution_class` defaults to `managed`); runtime
  dispatch is local to custom nodes; P2.6.2/P2.6.3/P2.6.5 and Studio files are untouched.
- **Application security:** static review is not represented as isolation; exact tenant/pin checks
  bracket dispatch; harness and unmarked adapters are rejected for production; returned patches are
  untrusted and validated before copy-on-success state mutation.
- **SRE:** feature flag defaults off, missing adapters deny, no socket/container/service is added,
  timeout/output termination is bounded, and unknown/late results cannot update state.

## Checks not run

- Repository-wide pytest and PostgreSQL test suite were not rerun; the focused affected suites plus
  the first-wave repository-wide baseline are the proportional evidence for this seam-only branch.
- No live web/Celery dispatch, crash/restart, broker outage or production sandbox probe.
- No seccomp/LSM/network namespace/OpenShift/gVisor/Kata/microVM evidence.

## Residual production gates

- Approved runner backend and deployment topology.
- Target-runtime RuntimeDefault seccomp/LSM, deny-all egress, read-only root, dropped-capability,
  non-root, PID/CPU/memory/scratch enforcement and escape-corpus evidence.
- Signed/pinned image lifecycle, vulnerability/SBOM process, capacity/reconciliation/kill-switch design.
- Security/platform acceptance of shared-kernel risk or selection of gVisor/Kata/microVM.
