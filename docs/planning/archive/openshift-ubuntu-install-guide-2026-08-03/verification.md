# Verification: OpenShift Ubuntu installation guide

| Check | Result | Evidence |
| --- | --- | --- |
| Focused and adjacent Python tests | Pass | 42 passed: external demo seeder/server, model provider and embedding adapter suites; final focused seeder/server rerun: 20 passed. |
| Ruff format and lint | Pass | Four changed Python modules/tests formatted; all selected security/style rules passed. |
| Mypy | Pass | No issues in 448 source files. |
| Django system check | Pass | No issues. |
| Migration drift | Pass | No changes detected. |
| YAML parse | Pass | Four OpenShift Templates parsed with the runtime PyYAML parser. |
| Restricted-SCC/resource invariant audit | Pass | Nine workloads/nine containers: non-root, read-only root, RuntimeDefault seccomp, no fixed UID, no privilege escalation, drop ALL, bounded `/tmp`, CPU/memory/ephemeral request+limit. |
| Shell syntax | Pass | Installer and embedded bootstrap Job script accepted by `/bin/sh -n`. |
| Demo image build | Pass | `deploy/external-demo.Dockerfile` built successfully. |
| Arbitrary UID/read-only smoke | Pass | Demo image ran as `uid=12345 gid=0` with read-only root/tmpfs and returned `/healthz` HTTP 200. |
| Secret/static scan | Pass | No real provider key, consumer token or operator password in scoped files; example contains placeholders only. |
| Diff hygiene | Pass | `git diff --check` clean at closure. |

## Acceptance criteria mapping

All nine acceptance criteria are implemented and offline/container verified. The target cluster must
still validate rendered admission, SCC mutation, quota, registry pull, Routes, CNI/egress, custom CA
and managed-service/provider connectivity.

## Security and authorization review

- Staff engineering: migration precedes rollout; application/static release ids are coupled; images
  are digest-only; provider profile revisions are immutable; Secret rotation forces rollout.
- Application security: no root/fixed UID/privilege/RBAC token, no plaintext Secret manifest, demo
  upstream requires explicit startup opt-ins, tokens remain server-side, tenant scope is installed
  before tenant-row seeding and provider destinations remain catalog/SSRF controlled.
- SRE: every container has requests/limits/probes where meaningful, one scheduler replica, bounded
  writable storage, bounded rollout waits, readiness gates, troubleshooting, upgrade/rollback and
  non-automatic uninstall boundaries.

## Data, migration and rollback

The installer requires separate migration and runtime database URLs. It runs only forward Django
migrations and never resets a database, bucket, PVC or namespace. Rollback restores prior immutable
application/static digests with their matching release id; database reversal requires separate
migration-specific approval.

## Concurrent workspace scope

Unrelated in-progress halfvec adapter/ADR/task changes appeared during implementation. They were
read only to avoid documenting a contradictory dimension limit and are not part of this task's
change ownership or final review.

## Checks not run

No live OpenShift cluster or `oc` client is available from this workstation; exact rendered-resource
admission/server-side dry run, SCC mutation, Route, CNI egress and managed-service connectivity
require the target environment. ShellCheck was not run: the available third-party container path was
rejected because mounting the repository into an untrusted image was not authorized; POSIX parsing
and manual shell review were completed instead.

## Remaining risks

- Resource sizing is a safe initial bound, not target load-test evidence.
- Environment-specific egress cannot be guessed from DNS names; platform review must supply exact
  policies without a permanent catch-all rule.
- Model/embedding APIs must be genuinely OpenAI-compatible, use trusted HTTPS and currently resolve
  to destinations accepted by the public-unicast SSRF policy.
- Custom CA, proxy/service-mesh, registry authentication, backups and managed-service availability
  remain target-platform responsibilities.

## Final status

Offline/container verified on 2026-08-03; target-cluster acceptance remains required before claiming
a live OpenShift deployment.
