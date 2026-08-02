# Verification: current-application-role-ui-audit

## Phase 2.9 closure update — 2026-08-02

All Phase 2.9-actionable findings in this baseline were subsequently implemented and verified. See
the [final closure evidence](../../planning/archive/phase-2-9-final-closure-2026-08-02/verification.md).
The results below remain the historical pre-fix evidence.

| Check | Result | Evidence / notes |
| --- | --- | --- |
| Live topology | Passed | Eight Compose services up; PostgreSQL/Redis/MinIO healthy; liveness and readiness HTTP 200 |
| Persistent model profile | Passed | Active `audit-gemini-chat` r1 using `gemini-3.6-flash`; real AgentHub provider response non-empty |
| Persistent embedding profile | Passed | Active `audit-gemini-embedding` r1, 3072 dimensions; normalized real vector and Demo Org grant |
| Index build/activation | Partial | Browser build succeeded with 1 document / 1 chunk and index v1 active; normal lifecycle omitted set-version activation and built-index link |
| Browser retrieval | Passed after audited bootstrap | Same UI returned the synthetic chunk after supplying the two missing lifecycle links; score and vector score displayed |
| Candidate compile | Passed | Six exact artifact pins; canonical preflight succeeded; candidate #7 compiled |
| Release eval/promotion | Passed outside UI | Eval 1/1 passed; #7 promoted active; UI lifecycle controls unreachable |
| Release rollback | Passed outside UI | #9 evaluated/promoted; unauthorized rollback 404; authorized rollback restored #7 and marked #9 rolled_back |
| Scenario external callability | Failed normal UI lifecycle | Active release + alias + binding still returned `SCENARIO_NOT_ALLOWED` while scenario remained draft; no activation UI |
| Sync/background runtime | Passed after scenario bootstrap | Sync 200/completed with 4 events; background 202/queued |
| Cancellation | Passed | Two immediate POSTs returned 200; queued run became cancelled with cancellation acknowledged |
| Consumer isolation | Passed | Foreign consumer status and cancel both returned 404 |
| Runtime operator UI | Failed | Other same-org scenario runs visible; exact run detail accessible; no pause/resume/cancel controls |
| Tool approvals | Passed | Approver accepted #1 and rejected #2/#3; runtime operator queue hid #3 and direct decision returned 403 |
| Second-tenant browser isolation | Passed | New tenant project readable by its viewer; Demo→isolation and isolation→Demo direct project probes both 404 |
| Tombstone/purge | Passed | Synthetic document tombstoned, unpinned, confirmed, and purged; one version removed and record absent |
| Connector workspace | Blocked by configuration/UI | No connector profiles/grants; no source wizard or connector profile provisioning route |
| Studio AI planner UI | Failed | Exact scenario editor can edit draft but AI panel is not rendered due organization-level `canWrite` gating |
| Studio AI provider API | Failed integration | Authorized request reached Gemini; fenced response caused `candidate_invalid_json`; no draft persisted |
| Frontend tests | Passed with warning | 8 files / 29 tests; existing React `act(...)` warning |
| Frontend typecheck/build | Passed | `tsc --noEmit` and Vite production build succeeded |
| Full SQLite backend | Passed | 1,047 passed, 60 PostgreSQL/pgvector-specific skipped, 204.86s |
| Full PostgreSQL backend | Failed | Initial profile: 1,088 passed, 5 skipped, 7 failed, 7 errors; environment-corrected targeted rerun reduced this to 4 genuine failures |
| PostgreSQL failure isolation | Failed | 13/17 targeted passed; 3 stale workflow wait tests call removed `allowed_roles`/`actor_roles` kwargs, and 1 non-owner middleware test lacks SELECT on `identity_platformresponsibilityassignment` |
| Ruff lint | Passed | `ruff check .` clean with pinned 0.15.21 |
| Ruff format | Failed pre-existing state | 11 files would be reformatted; no formatting changes made |
| Mypy | Failed pre-existing state | 22 errors in 12 files; includes stale wait-test signatures and typed mapping/form issues |
| Django/system checks | Passed | `manage.py check`, `compileall`, applied migration check, and migration drift check clean |
| Logs | Partial | No HTTP 500; expected 403/404 warnings and tracebacks plus known watchfiles nested-worktree permission traceback |

## Authorization evidence

- Exact allow/deny pairs used the same disposable objects.
- Unassigned release eval/promote/rollback attempts returned 404 without mutation.
- Runtime operator pending-approval decision returned 403 and remained pending until the approver rejected it.
- Consumer run status/cancel was exact-consumer scoped (foreign 404).
- Two tenant-specific project viewers produced bidirectional 404 for the foreign project.
- The same-tenant runtime disclosure remains a confirmed authorization defect despite passing tenant-separation tests.

## Provider and secret evidence

- The external Gemini key was read only from the user-authorized local `.env`, length-checked without value output, and injected only into process/container environment.
- No key, bearer token, cookie, or generated plaintext secret was written to task evidence.
- Model provider: non-empty response with recorded token counts.
- Embedding provider: one normalized 3072-dimensional vector.
- Studio authoring: response classification only (56 characters, 18 output tokens, starts with code fence); content was not logged.

## Data and audit evidence

- Three non-product bootstrap events were explicitly audited: scenario lifecycle activation, document-set-version activation, and built-index linkage. They were needed only because the corresponding UI/domain transitions are absent.
- Release, credential, run, approval, index, membership, responsibility, tombstone, and purge operations produced normal domain audit history.
- Synthetic document content contained no secrets or personal data.
- The purge target is unrecoverable by design; all other disposable local records are retained for reproduction.

## Remaining unverified path

Real connector egress remains unverified because no connector profile, grant, or credential exists and the console offers no provisioning path. Exercising an uncontrolled external connector would expand scope beyond the authorized local/Gemini systems.

## Post-audit governance and remediation planning

| Check | Result | Evidence / notes |
| --- | --- | --- |
| Mandatory browser gate | Passed (documentation) | `docs/ai/testing-rules.md`, `docs/ai/definition-of-done.md`, and manual-testing-guide section 10 require current-build UI/UX/authorization evidence after every product-development increment |
| Profile prerequisite stop rule | Passed (documentation) | Dependent lifecycle claims are explicitly blocked until the governed model/embedding/connector/worker prerequisite is proven; secrets and provider/document content are excluded from evidence |
| Role/tenant regression matrix | Passed (documentation) | Required rows cover permitted/forbidden actors, same-tenant cross-scope, cross-tenant, forged direct requests, functional errors, audit, browser console/network review, and UX/click/accessibility assessment |
| Remediation phase | Passed (planning) | Phase 2.9 separates seven dependency-ordered parts: P0 authorization/PostgreSQL and lifecycle integrity; P1 control/setup/AI parity; P2 UX and quality automation |
| Master-plan integration | Passed | Phase 2.9 is linked from current state and the component table without claiming implementation |
| Relative Markdown links | Passed | PowerShell link-target check across all changed planning/testing documents found no missing local targets |
| Whitespace/diff validation | Passed | `rg -n '[ \t]+$'` found no trailing whitespace; `git diff --check` passed |
| Runtime/product regression | N/A | Documentation and planning only; no application code, schema, configuration, dependency, or runtime state changed in this follow-up |

The Phase 2.9 plan preserves implementation approval gates for authorization, tenant isolation,
secret/profile policy, public contracts, and any migration. It is intended work, not evidence that
the audit defects are fixed.

## Final status

Audit and follow-up governance/planning complete. Product code is unchanged. The remaining work is
the separately planned Phase 2.9 implementation for the reported authorization/lifecycle/UI defects
and reproducible PostgreSQL/type/format quality failures.
