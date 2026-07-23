# Threat Model: Phase 2.8 Part 7 — Unified runs and kill-switch management

## Assets and actors

Tenant job/run metadata, trace/evidence, runtime availability, queued/waiting state, cancellation and
suspension authority, document-set quarantine/grant state, superadmin use,
audit integrity and operational performance. Actors include Global/Organization/Project Admins,
Scenario Editors, Document Set Managers, workers, automated safety controls and malicious members.

## Entry points and trust boundaries

Unified list filters/pagination, native detail/action links, dashboard KPI links, suspend/resume forms,
execution admission and worker transition claims. Query strings, active organization, record IDs,
reasons and worker task state are untrusted; native services and target tenant lineage remain
authoritative.

## Principal threats and mitigations

| Threat | Required mitigation |
| --- | --- |
| Union/projection leaks foreign metadata | Tenant-scope every native queryset before projection/filter/count |
| Displayed row grants unsupported action | Native detail/action service reauthorizes exact target and action |
| Filter causes unbounded/expensive query | Closed allowlist, date/page caps, indexed sort and measured query plans |
| Forged KPI/filter tenant ID widens scope | Server-constructed filters; active org only narrows authorized scope |
| Lower-scope admin flips broader/foreign switch | Exact object capability predicates and locked target row |
| Narrow resume overrides broader suspension | Full hierarchy checked independently; broader state dominates |
| Authoring role gains operational control | Explicitly deny Project Admin and Scenario Editor cancel/pause/resume |
| Runtime resume mutates release | Resume never changes release; release service independently authorizes |
| Lower role clears policy/automatic/admin pause | Record source/actor/privileged-resume flag and enforce provenance |
| Runtime control exposes document content | Safe metadata only; runtime control never grants content authority |
| Admin grants a controlled scenario document access | Only assigned DS Manager grants; superadmin intervention is specially audited |
| Daily operator relies on superadmin bypass | Non-superuser Global Admin; separate, guarded and alerted superadmin |
| Hidden temporary elevation bypass appears | No elevation/approval/temporary-access subsystem |
| Admission/worker races switch change | Check at admission and transactionally before every transition claim |
| Suspension loses/corrupts in-flight state | Cooperative boundary stop; durable checkpoint; no implicit cancellation |
| Audit outage permits unaudited control | Suspend/resume audit fail closed in transaction |
| Reason/log exposes sensitive data | Bounded safe reason validation; no payload/provider/content logs |

## Failure cases, audit and residual risks

Handle projection partial-source failure, deleted targets, cursor drift, DB timeout, concurrent switch
flips, worker crash after claim and terminal late results. Audit control changes with safe IDs and
trace; list views are not business-audited. A DB/control-plane outage may prevent both suspension and
resume; command/runbook fallback and fail-safe runtime behavior require SRE review.

## Required security tests

Cross-tenant rows/counts/filters/details; role/action and stop/resume-provenance matrices; forged
active org/KPI; pagination/date bounds; global/org/project/scenario precedence; Project Admin
publish/cancel/pause/resume denial; Scenario Editor cancel/pause/resume denial; policy resume denial;
document-content non-disclosure; quarantine
and retrieve-grant revocation; superadmin audit/alerts and absence of elevation paths; concurrent
admission/claim/resume/cancel; audit rollback; disabled tenant; redaction; PostgreSQL non-owner RLS
and query-performance denial cases.
