# Verification: P2.6.4 failure, retry and compensation

## Result

Implemented and verified on `codex/phase-2-6-p2-6-4-recovery` on 2026-07-17, then integrated into
`feat/foundation-sprint-0-1` through merge commit `b3f641d`.

## Evidence

| Check | Result |
| --- | --- |
| Current compiler/runtime/tool-boundary inspection | Complete |
| Task plan and threat model | Complete |
| Authorization/console-contract approval | Approved by user on 2026-07-17 |
| Compiler contract | v4 error routes, bounded transient retry and pinned compensation passed |
| Durable models | Attempt, compensation, recovery case and distinct approval records implemented |
| SQLite repository regression | `873 passed, 33 skipped` |
| Workflow regression | `172 passed, 1 PostgreSQL-only skip` |
| PostgreSQL workflow/tenancy regression | `188 passed, 3 SQLite-only skips` |
| PostgreSQL recovery FORCE RLS proof | Passed under a non-owner probe role |
| Migration forward/backward/forward | Fresh apply through `0008`, rollback to `0006`, reapply through `0008` passed |
| Recovery authorization | Author denied/audited; organization admin allowed only in tenant; high-risk compensation required two distinct admins |
| Console security | CSRF-less POST denied; exact revision/checksum and bounded reason enforced |
| Ruff lint/format | Passed; 394 files formatted |
| mypy | `Success: no issues found in 393 source files` |
| Django system check and migration drift | No issues; no changes detected |
| Post-merge full SQLite regression | `874 passed, 33 skipped` |
| Post-merge PostgreSQL workflow/tenancy regression | `189 passed, 3 SQLite-only skips` |
| Post-merge canonical infrastructure | PostgreSQL, Redis and MinIO reported healthy by Compose |

## Status

Implemented and verified. No production dependency or live egress was added.

## Checks not run

- No real provider/tool side effect was invoked; proxy and recovery tests remain deterministic.
- No live Celery worker kill/restart or Redis outage drill; durable transition/redelivery behavior is
  covered in tests and the live operational drill remains P2.6.11 closure work.
- No tool retry proof exists by design. Tool retry is compiler-rejected until a server-verifiable
  release-pinned idempotency/reconciliation contract is introduced.

## Final review

- **Staff engineer:** v4 is an explicit compatibility boundary; retries are bounded and durable;
  error routes and compensation targets are compile-time deterministic.
- **Application security:** unknown/outcome-unknown failures cannot be blindly repeated; admin
  actions resolve only system-created cases and cannot choose work/state; RLS and denial audit pass.
- **SRE:** cancellation closes recovery work; migration rollback/reapply and duplicate/terminal
  behavior pass. Live worker/broker drills remain explicit final-acceptance work.
