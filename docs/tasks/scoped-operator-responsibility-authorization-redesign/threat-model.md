# Threat Model: scoped-operator-responsibility-authorization-redesign

## Assets

- Human user identities and organization memberships.
- Platform, organization, project, scenario and document-set responsibility assignments.
- Effective authorization decisions and authority provenance.
- Project/scenario configuration, release metadata and runtime controls.
- Protected document content, chunks, retrieval grants and ingestion/index operations.
- Tool invocations, redacted approval context and approval decisions.
- Consumer identities/capabilities and optional verified human initiator identity.
- Audit events, security alerts, traces and authorization metrics.
- PostgreSQL, Redis and MinIO demo data targeted by the approved local reset.

## Actors

- Unauthenticated or inactive user.
- Active roleless organization member with no responsibilities.
- Organization administrator and organization auditor.
- Project viewer/administrator.
- Scenario viewer/editor/release manager/runtime operator/approver.
- Document-set metadata viewer/content reader/manager.
- Global administrator.
- Exceptional Django superadmin recovery identity.
- Authenticated machine consumer.
- Compromised or stale web/worker/CLI process.
- Malicious same-tenant user attempting sibling-scope access.
- Cross-tenant user or consumer.
- Local operator executing the destructive demo reset.

## Entry points

- Login/session and organization selection.
- Organization membership and responsibility management console forms.
- Project, scenario, release, runtime, document and evaluation console surfaces.
- Direct object URLs, selector/options endpoints and dashboard/count queries.
- Tool approval list/decision console and management commands.
- Gateway/MCP execution requests and server-owned execution context.
- Celery runtime/ingestion/evaluation tasks, resumptions and retries.
- Django models/services/migrations, seed command and PostgreSQL RLS.
- `scripts/local-stack.ps1 -Action Fresh`.

## Trust boundaries

- Directory/session authentication to active roleless membership.
- Membership to responsibility assignment; membership alone is not resource authority.
- Client locator/input to server-resolved organization and typed target lineage.
- Console/API/CLI/task caller to the central capability decision service.
- Application authorization to PostgreSQL FORCE RLS.
- Consumer identity to optional verified human initiator identity.
- Tool artifact policy to central approval authorization.
- Web process to worker/beat processes across deployment revisions.
- Local operator confirmation to destructive PostgreSQL/MinIO volume deletion.

## Data classifications

- Membership and assignment identifiers/provenance: internal security metadata.
- Usernames/directory identities: personal/internal.
- Approval target, tool reference and risk: tenant-confidential operational metadata.
- Document text/chunks and retrieval context: tenant-confidential or protected content.
- Credentials, tokens and secret references: secret.
- Stable reason codes, counts and low-cardinality metrics: internal operational data.
- Audit records: security/compliance evidence.

## Authentication

Human actions require an authenticated, active Django user. Machine invocations require the
existing authenticated consumer/token boundary. A consumer is never treated as a human user.
Optional `initiated_by_user` is accepted only from trusted server-owned context produced after
human authentication; public requests cannot forge it.

Django superuser remains a separate recovery identity and is not representable by membership or
responsibility assignment.

## Authorization

- Deny by default.
- Active membership is required for every tenant responsibility but grants only the safe
  organization shell.
- Every read and action requires an active, unexpired exact assignment mapped centrally to the
  requested capability.
- Target organization/project/scenario/document-set lineage is derived from persisted models.
- Responsibility and capability values are closed code-owned vocabularies.
- Assignment administration is itself capability-checked and scope-bounded.
- Approval requires exact scenario-approver assignment at decision time.
- Organization/global administrators do not implicitly receive approval or protected document
  content.
- UI hiding/filtering never substitutes for service/worker/CLI authorization.

## Tenant isolation

Every tenant assignment stores `organization_id`, validates membership and target lineage, and is
covered by PostgreSQL FORCE RLS. Application queries set the exact tenant context and filter before
returning labels, counts or existence signals. Platform/recovery paths use explicit authority
sources and retain alert/audit requirements.

No target scope is inferred from session-selected organization alone. Cross-tenant missing and
unauthorized targets return stable non-enumerating outcomes.

## External systems

- LDAP/AD supplies human authentication/directory identity but does not directly inject runtime
  responsibility strings in this task.
- PostgreSQL provides persistence and RLS.
- Redis/Celery transport server-owned execution context; stale workers are a cutover threat.
- MinIO contains disposable demo objects removed by the confirmed local reset.
- Tool endpoints remain behind the existing proxy/egress controls and are not changed here.

## Abuse cases

| Abuse case | Impact | Required mitigation |
| --- | --- | --- |
| Membership-only user enumerates all projects/scenarios | Tenant metadata disclosure | Assignment-scoped list/detail/count queries; direct URL denial tests |
| Same-tenant user forges sibling target ID | Unauthorized read/mutation | Trusted target resolution and exact scope assignment |
| Assignment references member/target from different organizations | Cross-tenant privilege escalation | Typed FKs, locked lineage validation, model constraints/tests and RLS |
| Revoked membership retains active assignments | Persistent unauthorized access | Membership as top-level deny; atomic assignment revocation; decision-time recheck |
| Expired/revoked approver decides an old pending request | Unauthorized side effect | Exact live scenario assignment recheck inside decision transaction |
| Organization admin approves without scenario assignment | Separation-of-duties failure | No implicit approval capability in org-admin mapping |
| Project admin grants themselves/high-risk scenario authority | Privilege escalation through delegation | Project admin may delegate viewer/editor only; org admin grants approval/release/runtime |
| One actor binds and grants document retrieval from both sides | Protected-content disclosure | Exact scenario requester/binder plus independent exact document-set manager approval |
| Tool artifact chooses a broad approver role | Policy-authored privilege widening | Remove `approver_roles`; central fixed responsibility requirement |
| Consumer subject collides with username | False self-approval denial or identity confusion | Typed consumer and human fields; never compare strings across actor classes |
| Public caller forges human initiator | Bypass or denial of approval | Initiator only from authenticated server-owned context; ignore client field |
| Unauthorized user sees pending approval metadata | Tool/risk/scenario disclosure | Scope approval queryset before rendering |
| Legacy helper grants after new-model deny | Cutover privilege widening | Atomic removal/static absence checks; no permissive fallback |
| Stale worker executes old approval contract | Authorization bypass or stuck runs | One version-matched fleet; stop/drain/restart and revision checks |
| Last organization admin is revoked concurrently | Administrative lockout | Row locks and last-effective-admin invariant |
| Last administrator expires without a replacement transaction | Administrative lockout | Global/org admin responsibilities cannot carry `expires_at` |
| Assignment audit fails but grant commits | Untraceable privilege | Required audit in same transaction; fail closed |
| Generic scope ID points to wrong model/tenant | IDOR/tenant escape | No generic FK; typed scope tables |
| Local `Fresh` targets wrong environment | Irreversible data loss | Canonical Compose/status inspection, typed confirmation, no routine `-Force`, production hard stop |

## Failure cases

- Authorization service unavailable or raises: deny; do not use legacy fallback.
- RLS context absent/invalid: deny or empty result; never broaden.
- Required audit persistence fails: roll back membership, assignment and approval mutations.
- Assignment expires during request: decision/action transaction rechecks current time.
- Membership revoked while action queued: worker re-authorizes before side effect.
- Tool approval already decided/expired/checksum changed: stable terminal denial.
- Human initiator cannot be resolved: preserve machine request but do not invent a human identity;
  exact scenario approver may decide unless another policy explicitly requires human provenance.
- No active scenario approver: request remains pending until expiry and emits safe operational
  readiness evidence; do not fall back to organization role.
- Mixed schema/code/worker revisions: deployment gate fails and fleet does not start.
- Fresh reset interrupted: rerun empty-environment recreation; do not attempt partial data salvage.

## Logging and audit risks

- Usernames, consumer subjects or assignment IDs used as metric labels create cardinality/privacy
  risk.
- Raw document/tool input in approval audit leaks protected content.
- Logging requested role/capability input can imply it was trusted.
- Missing assignment authority source makes incident reconstruction impossible.
- Logging reset credentials, volume paths derived from broad variables or secrets is unsafe.

Audit safe identifiers, actor type, exact actor/assignment/target public identifier, capability,
authorization outcome, stable reason and trace/request IDs. Approval audit stores checksum and safe
tool/risk identifiers, never raw input/secrets. Metrics use low-cardinality scope kind, capability,
outcome and reason only.

## Mitigations

- Closed responsibility/capability vocabulary and one decision boundary.
- Typed assignment tables with exact FKs; no generic targets.
- Active membership and assignment checked at every decision.
- Tenant-filtered querysets plus PostgreSQL FORCE RLS.
- Row locks and atomic audit-required mutation services.
- Exact scenario approval and redacted approval queue.
- Typed human/consumer identity and decision-time self-approval check.
- Atomic artifact/schema/caller/worker cutover.
- Static searches and graph-assisted inventory confirmed by direct inspection/tests.
- Clean disposable reset rather than ambiguous role backfill.
- Typed-confirmation local reset with live Compose/health inspection.
- Full negative authorization, RLS, concurrency, audit and worker tests.

## Residual risks

- A missed list/count/query path can disclose metadata until inventory and tests are complete.
- Hard-coded responsibility bundles require code deployment for policy changes.
- Exact scenario approvers can create operational bottlenecks or expiry without decision.
- Superadmin recovery remains powerful and depends on existing custody/alert controls.
- Local destructive reset remains irreversible after confirmation.
- Production adoption is unsupported until a separate inventory and migration plan is approved.

## Required security tests

- Membership-only, revoked, expired, inactive and disabled-organization denial.
- Exact capability matrix for every responsibility and exclusion.
- Same-org sibling and cross-org list/detail/count/selector/POST denial.
- Forged assignment membership/target and invalid responsibility/scope rejection.
- Membership/assignment revocation race and last-admin concurrency.
- Required audit failure rollback for membership, assignment and approval.
- PostgreSQL non-owner FORCE RLS for all assignment tables.
- Scenario A/B approval visibility and decision isolation.
- Autonomous consumer versus verified human initiator self-approval behavior.
- Consumer-subject/username collision remains distinct.
- Revoked/expired assignment before decision, expiry/checksum/concurrent decision.
- Stale/mixed worker contract deployment denial.
- Static absence of legacy runtime role and approval actor contracts.
- Fresh empty-database migrate/seed plus exact-target destructive reset rehearsal in a disposable
  environment.
