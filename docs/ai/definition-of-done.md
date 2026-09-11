# Definition of Done

## Status model

| Status | Meaning |
| --- | --- |
| Planned | Scope, criteria, risks, and approach are recorded. |
| In progress | Work is active and the plan reflects reality. |
| Implemented | Code/content is written; all verification may not be complete. |
| Verified | Required tests and controls ran successfully with recorded evidence. |
| Completed | Verification, documentation, risk report, and required human review are complete. |
| Blocked | A named dependency prevents progress; owner and unblock condition are recorded. |

`Implemented` is never evidence of correctness. `Verified` requires independent command/test evidence. `Completed` additionally requires documentation and review closure.

## Completion checklist

- [ ] Acceptance criteria are mapped to evidence and met; no out-of-scope change exists.
- [ ] Security review and applicable authorization negative/cross-tenant tests passed.
- [ ] Sensitive data is absent from logs; required audit events were verified.
- [ ] Repository-applicable formatter, linter, type-check, unit, integration, contract, security, secret, and dependency checks passed.
- [ ] The mandatory post-development browser UI/UX/authorization gate ran against the current build; matched role allow/deny and applicable same-tenant cross-scope/cross-tenant evidence, console/network review, click-count/usability findings, and any justified `N/A` rows are recorded.
- [ ] Migrations and compatibility/rollback behavior were verified when applicable.
- [ ] Operational behavior, monitoring, failure handling, and rollback are documented.
- [ ] README/current architecture docs reflect actual behavior.
- [ ] A durable decision has an ADR when needed.
- [ ] The task verification record contains commands, results, evidence, and skipped checks.
- [ ] Final diff was reviewed for architecture, security, authorization, privacy, observability, and operations.
- [ ] Remaining risks, unverified assumptions, and manual review requirements are explicit.

Mark non-applicable checks `N/A` with a reason. A missing tool is a reported gap, never a passing result.
