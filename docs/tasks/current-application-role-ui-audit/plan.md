# Task Plan: current-application-role-ui-audit

## Task summary
Start the current local application, inventory operator capabilities by role, identify capabilities without a console surface, and manually test reachable console journeys for functional errors and usability.

## Background
The requested review spans repository authorization policy, console routes/templates, and live browser behavior. Static declarations are navigation evidence; code, tests, and live behavior are authoritative.

## Scope
- Verify the supported local Compose topology and health state.
- Inventory current operator roles and their allowed actions.
- Map allowed actions to console UI entry points.
- Exercise representative permitted and denied journeys in the browser.
- Verify local Gemini LLM and embedding configuration; when absent, temporarily inject the explicitly authorized key from `C:\Users\kuzuc\Desktop\engineer-team\deploy\.env` without persisting or printing it, then run bounded live smoke tests.
- Record functional and UX findings without changing product behavior.
- Re-run the audit after the scoped-responsibility test migration, using disposable local identities and records to exercise safe create/update/revoke/cancel-style UI actions and both allow/deny paths.
- Provision persistent local Gemini model and embedding profiles, grant them to the disposable demo tenant, and treat successful real provider calls as a hard prerequisite for all remaining index/release/runtime/approval/cross-tenant checks.
- Complete the previously unverified second-tenant, index activation, release lifecycle, active-run control, and approval-decision paths with disposable local records.
- Convert the completed audit into a mandatory post-development browser UI/authorization regression control in the authoritative testing and completion documentation.
- Create a separate, dependency-ordered remediation phase plan for the confirmed authorization, lifecycle, functional, quality, and UX gaps, and link it from the master plan.

## Non-goals
- Production access or production data.
- Destructive local reset.
- Authorization, UI, dependency, migration, or public API changes.
- Destructive operations on non-synthetic records.
- Implementing the remediation phase or changing current product behavior as part of this documentation task.

## Acceptance criteria
- The current application is reachable and its service state is recorded.
- A role/capability matrix is supported by code and live evidence.
- Capabilities with no usable console path are explicitly identified.
- Reachable role-specific journeys are tested for errors and usability.
- Assumptions, untested paths, risks, and required follow-up are recorded.
- The post-development UI gate states when it applies, the minimum role/allow/deny/cross-tenant/browser coverage, required evidence, and the rule that a failed or unexecuted applicable check cannot be reported as verified.
- A separately linked component phase orders every confirmed audit finding into independently deliverable parts with acceptance, security, authorization, data, observability, testing, rollout, and rollback expectations.

## Affected components
Read-only review of `apps/identity`, `apps/console`, related domain services/tests/templates, the frontend builder, local Compose, operator documentation, testing governance, and project/component planning records.

## Interfaces affected
No runtime interface. The development process gains a mandatory post-development browser UI/authorization verification gate.

## Data impact
Manual tests may create or update disposable demo-tenant records when a safe UI journey requires it. The user's request to complete all previously unverified paths authorized a single confirmed synthetic tombstone/purge lifecycle; no reset or production data is authorized. The user explicitly authorized reading the Gemini key from the named local `.env`; its value must not be printed, committed, logged, or copied into task records.

Persistent local profile catalogs, tenant grants, disposable second-tenant records, releases, runs, approvals and indexes may be created. Provider secrets remain environment-only and must not be stored in database fields or task evidence.

## Security impact
The review checks authentication, role gating, tenant scoping, denial behavior, and inadvertent UI disclosure.

## Authorization impact
No policy change. Current server-side authorization and UI affordance parity are assessed.

## Observability impact
Existing logs and visible error responses may be inspected. No logging configuration change.

## Migration impact
No migration is planned. Existing migrations may be applied only through the supported non-destructive local startup command.

## Dependencies
Docker Compose, the repository-owned local stack command, seeded local demo users, and the in-app browser.

## Implementation steps
1. Inspect instructions, topology, active state, and relevant plans/docs.
2. Start/update the supported stack while preserving local data.
3. Derive the authorization and UI coverage matrices from source and tests.
4. Test representative browser journeys for each available role.
5. Review evidence through staff-engineering, application-security, and SRE lenses.
6. Record verification and report.
7. Add the reusable browser gate to testing governance and the manual testing guide.
8. Plan the audit remediation as a separate prioritized phase and link it into the master plan.

## Test plan
- Compose service and liveness checks.
- Logged-out redirect and login/logout.
- Role-specific navigation, permitted mutations, and denied actions.
- Representative cross-role UI affordance checks.
- Browser console/network-visible failures and responsive/usability inspection where supported.
- Count interaction steps and assess discoverability for user membership/responsibility, project, scenario, consumer/token/binding, document-set and runtime journeys.

## Rollout plan
Documentation takes effect when merged: every subsequent development task must apply the new gate or record a justified non-applicability decision. Remediation parts remain planned until separately approved and implemented.

## Rollback plan
The documentation change can be reverted without runtime/data impact. Any disposable demo mutation will be explicitly noted and reversed through the UI when practical.

## Risks
- Existing local data may differ from seed assumptions.
- Some capabilities require external providers, credentials, or long-running workers and may not be safely executable.
- UI absence does not prove server-side absence; route and policy checks are required.
- Browser coverage is representative rather than combinatorially exhaustive.
- Live provider configuration changes application egress behavior and requires a controlled Compose restart; incorrect model dimensions or provider paths can create failed ingestion/runtime jobs.
- Release, index and approval tests generate durable local audit/domain records that may not have a reversible delete UI.
- Treating the browser gate as a generic smoke test could miss exact-scope authorization regressions; the documented matrix must require matched permitted/denied actors and cross-tenant probes.
- Treating all findings as one implementation batch would mix security containment with UX polish and weaken rollback; the follow-up phase must preserve dependency and priority boundaries.

## Open questions
- Real connector egress remains unavailable because no connector profile, grant, or credential exists and no provisioning UI is exposed.

## Status
Completed: audit evidence, mandatory post-development browser gate, and the linked Phase 2.9
remediation plan are recorded and documentation-verified.

## Completion criteria
Evidence is recorded in `verification.md`; findings distinguish implemented, browser-verified, statically verified, and unverified behavior.
