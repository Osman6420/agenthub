# Verification: Phase 2.8 Part 7 — Unified runs and kill-switch management

> **Status: Not yet verified.**

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Unified projection/filter tests | To be recorded | Not run | — | Every native job kind |
| Dashboard KPI target parity | To be recorded | Not run | — | Exact records represented |
| Native detail/action auth | To be recorded | Not run | — | No universal cancellation |
| Kill-switch service/migration | To be recorded | Not run | — | Preserve global/org controls |
| Concurrency/in-flight behavior | To be recorded | Not run | — | Admit/claim/resume/cancel races |
| PostgreSQL RLS/performance | To be recorded | Not run | — | Non-owner and query plans |
| Audit/redaction/metrics | To be recorded | Not run | — | Fail closed and bounded labels |
| Full quality/browser/accessibility | To be recorded | Not run | — | Ruff, mypy, Django, responsive UX |

## Required evidence and review

Record native-versus-projection count samples, filter/page bounds, cross-tenant denial, action matrix,
global precedence, durable state across suspension and audit failure rollback. Staff reviews read
model/migration; AppSec reviews metadata/action/control authority; SRE reviews races, fail-safe
behavior, performance and runbook; UX reviews status and suspension explanations.

## Checks not run and remaining risks

None evaluated. List unavailable scale/load/PostgreSQL/browser/worker checks and accepted operational
risks before Verified.

## Final status

**Planned / not verified.**
