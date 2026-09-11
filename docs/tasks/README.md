# Task Documentation

Create `docs/tasks/<task-id>/` from [`template/`](template/plan.md) when work affects multiple files/components; changes authentication, authorization, tenant isolation, a public API, or a production dependency; includes a migration; addresses a critical/security bug; creates operational risk; or requires multiple implementation phases. A typo or low-risk localized edit does not require a task directory.

Before implementation, tailor `plan.md` and complete `threat-model.md` in proportion to risk. Record local decisions during work and update the plan when assumptions change. Record commands and evidence in `verification.md`. At completion, update current-state docs, promote durable decisions to ADRs, update the master plan, and follow the [archive policy](../planning/archive/README.md).
