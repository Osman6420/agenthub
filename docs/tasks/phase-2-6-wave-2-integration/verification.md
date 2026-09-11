# Verification: Phase 2.6 second-wave integration gate

## Result

Verified on `feat/foundation-sprint-0-1` on 2026-07-17. The merged P2.6.2, P2.6.3, P2.6.5 and
P2.6.8 runtime-seam changes pass the PostgreSQL migration, RLS, lifecycle, static and repository
regression gates. Child composition and reviewed Python execution remain disabled by default.

## Automated evidence

| Check | Result |
| --- | --- |
| Compose state and health | PostgreSQL, Redis and MinIO healthy; `/v1/health/live` returned 200 |
| PostgreSQL migration graph | Fresh temporary database applied all migrations through `workflows.0006` |
| PostgreSQL rollback/forward drill | `workflows.0006 -> 0003 -> 0006` passed; temporary database removed |
| PostgreSQL workflow/RLS integration suite | `51 passed, 2 skipped` (the skips assert SQLite-only behavior) |
| Workflow and tenancy PostgreSQL suite | `179 passed, 3 skipped` |
| Control-plane PostgreSQL suite | `530 passed` |
| Data-plane PostgreSQL suite | `183 passed, 2 skipped` with canonical local MinIO configuration |
| Repository PostgreSQL regression total | `892 passed, 5 skipped` across non-overlapping application groups |
| Combined runtime lifecycle coverage | Parallel cancellation/late result, timer recovery, wait replay, child idempotency/cancellation/late result and cross-tenant RLS passed |
| Migration drift | `No changes detected` |
| Ruff lint and format | Passed; 391 files already formatted |
| mypy | `Success: no issues found in 390 source files` |
| Django system check | No issues |
| `git diff --check` | Passed |

## Checks not run

- No production-like Python sandbox escape test; P2.6.8 execution remains fail-closed and inactive.
- No live Celery worker kill/restart, Redis outage or broker-redelivery drill; these remain activation
  and P2.6.11 operational-closure work.
- No browser/Studio journey; this gate covers the merged backend runtime wave.
- The first repository-wide PostgreSQL invocation exceeded the five-minute command bound with no
  buffered result. The same complete application set was rerun as three non-overlapping groups.
- The first data-plane attempt lacked host-mode MinIO credentials and failed with
  `NoCredentialsError`; it passed after rerunning with the manual guide's canonical local object
  store configuration. No credential values are recorded here.

## Final review

- **Staff engineer:** shared compiler/runtime/state-machine behavior and the linear `0004`–`0006`
  migration chain were reviewed; no sibling implementation was silently dropped.
- **Application security:** non-owner PostgreSQL RLS probes, cross-tenant denials, terminal guards,
  capability attenuation and fail-closed Python execution passed or remain inactive by design.
- **SRE:** fresh apply, rollback and re-apply passed; duplicate, cancellation, late-result and timer
  recovery tests passed. Live worker/broker failure drills remain explicitly deferred.

## Status

Second parallel-wave integration gate closed. P2.6.4 may begin.
