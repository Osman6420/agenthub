# Verification: phase-2-6-authoring-and-python-nodes

This record covers only the first P2.6.8 parallel-wave isolation spike, ADR and inert contracts,
integrated through merge commit `dbc53ef`. P2.6.8 runtime execution is not implemented or verified.
P2.6.9 is implemented and verified in its separate task and the
[first-wave integration record](../phase-2-6-wave-1-integration/verification.md).

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Exact branch baseline | `git show --no-patch --format="%H %D %s" 88fc203` and worktree status | Pass | Branch `phase-2-6/p2-6-8-isolation-spike` began at `88fc2038b2c11ed04104b9b7b2eeec2d3e8d0e58` | Separate worktree; shared checkout branch unchanged |
| Live Compose state | `docker compose -f deploy/compose/docker-compose.yml ps` | Pass | PostgreSQL, Redis and MinIO healthy; no web/worker/runner service listed | Read-only state check per manual guide section 0 |
| Runtime inventory | `docker version ...`; `docker info ...` | Conditional | Engine 27.3.1 Linux/amd64, cgroup v2, default `runc`; no gVisor/Kata runtime; security option reports `seccomp,profile=unconfined` | The unconfined posture fails ADR-0011 production minimum |
| Inert sandbox primitive probe | `docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 16 --memory 64m --cpus 0.25 --tmpfs /tmp:rw,noexec,nosuid,size=1m --user 65532:65532 python:3.13-slim ...` | Pass for local primitives | UID/GID 65532; minimal base-image env; root write `OSError`; scratch write `ok`; network connect `OSError` | Synthetic capability check only; no tenant source, application mount, credential or network |
| JSON fixture parse | `python -c "...json.loads..."` | Pass | `parsed 3` under host Python 3.14 | All inert JSON fixtures parsed; repository venv launcher was unavailable |
| JSON Schema metaschema validation | `python -c "...jsonschema...check_schema..."` | Pass | `metaschemas-valid 2` under host Python 3.14 | Existing host `jsonschema`; no package installed |
| Documentation links | PowerShell relative Markdown-link check over changed records | Pass | `markdown-relative-links-valid` | Local relative targets exist |
| Whitespace | `git diff --check` | Pass | No output | Working-tree diff |
| Staged scope | staged-name check rejecting `apps`, `config`, `deploy`, `frontend`, dependency/lock files | Pass | `scope-check-pass: docs-only` | 11 documentation/inert fixture files only |
| Targeted secret patterns | `rg` over changed task/ADR records for private keys, access keys, credential-bearing DB URLs and literal AWS secret assignment | Pass | `targeted-secret-pattern-scan-pass` | Repository-wide dedicated secret scanner is not configured |
| Staged whitespace | `git diff --cached --check` | Pass | No output | Includes new files |

## Acceptance criteria mapping

| First-wave criterion | Status | Evidence |
| --- | --- | --- |
| Managed/Python terminology is unambiguous | Implemented | ADR-0011 and `python-node-contracts.md`; existing persisted/runtime contract unchanged |
| Minimum separate runner and stronger-sandbox decision | Implemented, approval pending | `isolation-spike.md` decision matrix and ADR-0011 Proposed |
| Lifecycle and exact checksum binding | Implemented as inert contract | ADR-0011 and `python-node-contracts.md` |
| Automated security review/report contract | Implemented as inert contract | Rule families and `python-node-security-review-report.schema.json` |
| Source storage, encryption, retention and view options | Decision-ready, approval pending | ADR-0011 and contract option matrix |
| Active/disabled/in-flight behavior | Implemented as proposed decision | ADR-0011; owner approval still required |
| P2.6.9-safe public catalog | Implemented as inert contract | `python-node-public-catalog.schema.json` |
| Probe plan and negative corpus | Implemented, not executed | `isolation-spike.md` and `python-node-negative-sandbox-corpus.json` |
| Tenant Python runtime | Intentionally not implemented | No application, migration, API, dependency or deployment file changed |

The broader task-plan acceptance criteria for authorization enforcement, persistence, compiler,
runtime, Studio and P2.6.9 remain open for their owning branches.

## Security requirement mapping

- The spike rejects in-process, shared-credential and unconfined execution.
- Local evidence proves only selected OCI primitives; it explicitly does not claim kernel escape,
  target OpenShift network policy, seccomp/LSM, resource enforcement or production readiness.
- Exact immutable revision/report/review/activation checksums and scanner-error fail-closed behavior
  are specified.
- The negative corpus covers static policy, environment/filesystem/network escape, resource bombs
  and protocol substitution/replay/cancellation. It remains inert until an approved harness exists.
- Source/raw IO/stderr are prohibited from catalog, audit, logs, metrics and traces.

## Authorization tests

Not run and not applicable to this documentation-only branch. No authorization predicate or API was
changed. The proposed author/source-reviewer/activator/admin/auditor matrix requires explicit owner
approval and denial tests in the control-plane branch.

## Cross-tenant tests

Not run; no persistence or query surface exists. The contracts require direct organization lineage,
same-tenant constraints, FORCE RLS/non-owner verification and indistinguishable denial in the later
implementation.

## Logging and redaction tests

Not run; no logging path exists. The report/catalog schemas prohibit raw source, raw IO, scanner
output, storage locators, endpoints, credentials and review rationale.

## Audit event tests

Not run; no lifecycle mutation exists. Review, activation, disable and source view are specified as
fail-closed required audit actions for later implementation.

## Migration verification

N/A. No model or migration was created. `manage.py makemigrations --check --dry-run` was not run for
this docs-only change; the repository Python 3.13 venv launcher failed with the documented Windows
`A specified logon session does not exist` condition.

## Behavior comparison with base branch

Runtime, public/operator APIs, authorization, database schema, dependencies and deployment topology
are identical to `88fc203`. This branch adds only proposed architecture, planning, threat/verification
records and inert JSON schemas/corpus.

## Checks not run

- The negative corpus was not executed because no approved isolated harness exists; running it in
  Django/Celery/managed-node/ordinary CI is prohibited.
- Target OpenShift seccomp/LSM/network/resource/admission, image-signing/SBOM/vulnerability,
  cancellation/reconciliation, cold-start/load and gVisor/Kata/microVM checks were unavailable.
- No live tenant source, production data, external network or production system was accessed.
- Ruff, mypy, Django checks, compileall and pytest were not run because no Python/application code,
  model, migration, settings, dependency or deployment file changed. The residual risk is limited
  to documentation/contract inconsistency; JSON, link, scope, secret-pattern and diff checks cover
  the changed artifacts.

## Remaining risks

- Shared-kernel OCI isolation retains kernel escape risk.
- Local Docker reports unconfined seccomp and is not an acceptable production runner.
- Source KMS/object-store, role predicates, retention periods, module allowlist, numeric budgets,
  image ownership and runner protocol/topology are proposed but unapproved.
- The machine-readable catalog schema permits bounded generic JSON Schema summaries; semantic
  closure and truncation algorithms still need P2.6.9/integration-owner review.

## Human review required

- Security/platform acceptance of ADR-0011 and shared-kernel residual risk, or selection of a
  stronger runtime.
- Authorization/product approval of source reviewer, separate activation and emergency-kill roles.
- Data/privacy approval of KMS/object storage, backup, legal hold, retention and purge.
- SRE approval of queue/control-plane topology, image patch owner, resource budgets, capacity,
  reconciliation, kill switch and rollout evidence.
- Architecture/P2.6.9 owner acceptance of the public catalog schema.
- Dependency/supply-chain approval before any scanner or sandbox runtime/image is added.

## Final status

Verified for the first P2.6.8 documentation/contract scope; owner acceptance remains pending.
Runtime execution remains blocked by ADR acceptance, target-platform
evidence, P2.6.1 and the owner approvals listed above.
