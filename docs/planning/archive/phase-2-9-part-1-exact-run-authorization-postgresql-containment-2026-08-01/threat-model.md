# Threat Model: Phase 2.9 Part 1 — Exact run authorization and PostgreSQL containment

## Assets

Run existence, identifiers, scenario/project/organization lineage, consumer/actor metadata,
timestamps, status/error/reason codes, event names and counts, nested branch/join/wait/compensation
metadata, cancellation/recovery authority, responsibility assignments, tenant scope, PostgreSQL
role privileges and security/business audit integrity.

Payloads, checkpoints, execution context, wait data, prompts, provider output, document content and
credentials are higher-sensitivity adjacent assets that must never enter this console surface or its
evidence.

## Actors

Unauthenticated or inactive users; active member without responsibility; Global and Organization
Administrators; Organization Auditor; Project Administrator/Viewer; Scenario Viewer, Editor,
Release Manager, Runtime Operator and Approver; revoked/expired assignees; consumer identities;
workers; the PostgreSQL owner/migration role; and the non-owner application role.

## Entry points

- `/console/runs/` query filters and pagination.
- `/console/workflow-runs/` compatibility list.
- Workflow-run detail, cancel and recovery URLs/forms.
- Dashboard run counts and links.
- ORM relations for run events, waits, branches, joins, children and compensations.
- Tenant middleware/platform-admin detection and responsibility queries.
- PostgreSQL role provisioning, readiness checks and temporary non-owner test roles.

## Trust boundaries

Browser/session to Django; active-organization navigation state to persisted tenant membership;
membership to exact typed responsibility; list projection to native model querysets; run identifier
to persisted run/scenario lineage; read visibility to action authorization; Django ORM to PostgreSQL
non-owner role and FORCE RLS policies; application/security audit to its restricted readers.

Active organization, route/query/form identifiers, visible controls, client roles and submitted
reason text are untrusted and cannot grant authority.

## Data classifications

- Internal tenant metadata: run IDs, scenario/project lineage, statuses, timestamps and safe reason
  codes.
- Confidential operational/security data: consumer/actor references, event sequence/names,
  responsibility assignments, authorization decisions and audit events.
- Restricted and excluded: payloads, checkpoints, wait bodies, documents, prompts/responses,
  credentials, tokens, cookies and provider errors/content.

## Authentication

Existing Django session authentication remains unchanged. Authentication proves identity only.
Inactive users are denied; no client-supplied role or tenant claim is accepted. Consumer API
authentication remains a separate contract and is not broadened by a human console session.

## Authorization

The central persisted capability model is authoritative. Exact scenario runtime responsibility
grants `runtime.view`/`runtime.cancel` only for that scenario. Organization Administrator/Auditor
scope is organization-wide according to the existing capability map; Auditor is read-only. Project
and neighboring scenario responsibilities do not inherit runtime visibility.

Lists begin from an authorized queryset. Details resolve through the same queryset before nested
relations are accessed. Mutations then reauthorize the exact action against trusted persisted
organization/project/scenario targets. Invisible targets return 404; a visible target with a denied
action returns 403 and a redacted audit outcome.

## Tenant isolation

Application authorization is required in addition to PostgreSQL tenant RLS. PostgreSQL scope limits
which organizations the non-owner role can access; it does not encode exact scenario responsibility.
Both layers must pass independently. Tenant context is established from authenticated membership or
platform authority and must not be widened after resolving an unrestricted run identifier.

Protected run and organization-keyed responsibility tables retain FORCE RLS with the canonical
tenant predicate. The platform responsibility table has no tenant key and is used during bootstrap;
it must remain least-privilege and application-authorized rather than receiving a fabricated tenant
policy.

## External systems

None. This task uses local Django/PostgreSQL and browser surfaces only. No production data, provider,
connector, internet egress or new dependency is required.

## Abuse cases

| Threat | Required mitigation |
| --- | --- |
| Exact runtime operator enumerates another scenario's runs | Set-based exact scenario scope before list/count/filter/page |
| Guessed UUID opens a redacted foreign detail | Resolve through authorized queryset; uniform 404 before relation reads |
| Active organization widens authority | Use it only to narrow preauthorized native querysets |
| Hidden rows alter pagination/counts | Filter authorization before aggregation, ordering and pagination |
| Unified execution access exposes other job families | Apply native authorization independently per family |
| Read visibility grants cancellation/recovery | Separate exact action authorization after visible target resolution |
| Revoked/expired assignment remains cached | Query active status, membership/user state and expiry server-side |
| Forged scenario/filter ID widens list | Validate filter target inside authorized scope; reject safely |
| Platform-admin bootstrap query fails under app role | Canonical minimal privilege manifest/readiness test; no owner bypass |
| Broad grant masks the test failure | Compare exact SQL operations and deny owner/superuser/BYPASSRLS/default grants |
| RLS is added to a lineage-free platform table | Keep bootstrap table outside tenant policy unless approved schema supplies trustworthy lineage |
| Denial audit leaks target metadata | Stable codes and bounded IDs only; exclude labels, actor/consumer and event/payload data |
| Audit failure permits mutation | Mutation remains denied; surface audit failure according to reviewed operational policy |
| Query design causes per-row authorization load | Set-based predicates, bounded pages and measured query count/plan |

## Failure cases

Missing or stale responsibility assignment; organization disabled between list and mutation;
expired assignment during a session; hidden target deleted concurrently; invalid UUID/filter;
PostgreSQL grant missing; empty/wrong tenant scope; RLS helper unavailable; audit persistence outage;
query timeout; role reset/transaction-local scope leakage; and partial rollout where one run surface
uses the old organization-only predicate.

Failures default to no rows/404/403 and no mutation. A database authorization failure is not retried
under a stronger role. Rollback never restores the confirmed disclosure.

## Logging and audit risks

Expected 403/404 paths can create traceback noise or disclose route/identifier details. Denied
mutations need security evidence but must not copy run labels, consumer/actor identities, event
names, payloads, checkpoints or provider errors. Request/trace correlation and stable reason/source
codes should be retained; high-cardinality identifiers must not become metric labels.

## Mitigations

- One canonical authorized-run queryset/target resolver reused by list/detail/control paths.
- Native authorization per operation family and exact action checks for mutations.
- Uniform non-disclosing response semantics with nested metadata loaded only after authorization.
- Active/unexpired/status-aware persisted assignment predicates; no session/client authority.
- PostgreSQL non-owner `NOBYPASSRLS` tests, FORCE RLS assertions, transaction-local scope reset and
  canonical privilege drift checks.
- Redacted audit schemas and explicit audit-failure behavior.
- Bounded filters/pages/date windows, set-based queries and query-plan/count review.
- Matched same-tenant and cross-tenant role tests plus mandatory current-build browser evidence.

## Residual risks

PostgreSQL tenant RLS cannot by itself prove scenario-level authorization, so application predicates
remain a critical control. A new run surface or projection family can bypass the shared scope if it
does not use the canonical boundary; reference/search and regression review are required. The
platform assignment table remains readable to the application role as bootstrap authorization
metadata and depends on application-layer non-disclosure and restricted database credentials.

## Required security tests

- Exact runtime operator allow on assigned scenario and 404 on a second same-tenant scenario.
- Two-way cross-tenant list/detail/direct-URL isolation.
- Membership-only, project roles, neighboring scenario roles, inactive user, inactive/revoked/
  expired assignment and disabled-organization behavior.
- Organization Admin/Auditor read allowance; Auditor cancel/recovery denial and redacted audit.
- Exact runtime cancel allow, terminal/idempotent behavior and unauthorized POST non-mutation.
- Unified projection filter/count/page isolation and non-execution family non-disclosure.
- Nested event/branch/join/wait/child/compensation metadata never queried/rendered after denial.
- PostgreSQL non-owner allow/deny matrix, FORCE RLS/policy/helper/grant readiness and transaction
  scope reset; verify no DELETE, owner, superuser, `BYPASSRLS` or broad default privilege.
- Audit persistence failure keeps the action denied and emits safe operational evidence.
- Response/log/audit/body checks for payload, checkpoint, consumer/actor, event-name and secret
  markers.
