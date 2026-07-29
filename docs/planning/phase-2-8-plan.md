# AgentHub — Phase 2.8 Plan

> **Status: In progress.** Parts 1–3 are verified and owner-accepted. Parts 4–7 are implemented
> and automated/offline verified; remaining browser/live-provider owner acceptance is tracked by
> each part.
> This is a program plan:
> every remaining part owns a
> separate plan, threat model, verification record and acceptance gate. Planned behavior must not
> be described as current behavior before its part is implemented and verified.

## Purpose and target experience

Phase 2.8 turns the operator console into an organization-scoped, task-oriented product and then
removes the runtime distinctions that currently force users to understand internal RAG, workflow,
agent, artifact and run models.

The product hierarchy is `Organization → Project → Scenario`. Document sets are organization-owned
reusable resources. Artifacts, releases, index versions and run events remain immutable or governed
implementation records, but are selected and inspected from the task context that owns them.

The phase deliberately contains one platform rework: RAG, workflow and agent execution converge on
one workflow DSL, compiler, runtime and persistent Run model. This is not a UI-only rename. It
changes the authoring contract, AI-authoring guide, release compiler, gateway, evaluation,
observability and migrations, and therefore has its own staged acceptance gates.

## Delivery structure and dependencies

1. **Part 1 — Console information architecture and UX foundation — Verified.** Task navigation,
   contextual project/scenario pages, exact health-result lists, persistent shell, organization
   switcher, explanatory copy and accessibility foundation. Evidence is archived in
   [`phase-2-8-part-1-console-information-architecture`](archive/phase-2-8-part-1-console-information-architecture-2026-07-22/plan.md).
2. **Part 2 — Organization, user and access management — Verified.** Removed the cross-organization
   workspace state, add organization creation and user-role assignment, introduce the single-role
   document manager, and make creation forms derive their parent scope from trusted context.
3. **Part 2.1 — Scoped authorization and superadmin recovery — Verified.** The central capability
   service, delegated assignments, scenario-to-document-set grants, responsive Access UI and
   superadmin recovery controls are complete. See the
   [Part 2.1 archive](archive/phase-2-8-part-2-1-scoped-authorization-superadmin-recovery-2026-07-24/plan.md).
4. **Part 3 — Unified workflow engine — Verified.** One `workflow_definition`, compiler, runtime,
   Run/Event model and public run surface now govern RAG, workflow and agent execution.
5. **Part 4 — Scenario authoring, reusable artifacts and release experience — Implemented and
   automated/offline verified.** Preset-led scenario creation, contextual Studio, typed exact
   artifact selectors with logical/version descriptions, compiler-derived invocation guidance and
   governed AI-authoring preflight are implemented. Browser/live-provider owner acceptance remains.
6. **Part 5 — Document profiles, document manager and index automation — Implemented and
   automated/offline verified.** Set-only document management, exact chunking/retrieval profiles,
   keyword/vector/hybrid search, opt-in summary-to-document-to-content routing, optional
   provenance-bound summaries and idempotent staged index preparation are implemented; activation
   remains explicit. Destructive cleanup is not authorized.
7. **Part 6 — Question sets and retrieval/answer evaluation — Implemented and automated
   verified.** Reusable immutable-versioned question sets, exact-target document retrieval
   diagnostics, exact-release scenario answer evaluation, one-off asks and separate
   retrieval/answer quality measures are implemented. Optional LLM judging remains disabled until
   an approved pinned profile/prompt and privacy/cost review are supplied.
8. **Part 7 — Unified runs and kill-switch management — Implemented and automated/offline
   verified.** One bounded filterable operational projection spans execution, evaluation,
   ingestion, index-build and connector-sync jobs. Exact platform/organization/project/scenario
   runtime controls, native execution cancellation, document-set quarantine, audit rollback,
   bounded metrics and cooperative transition enforcement are implemented. Authenticated browser
   owner acceptance and production-scale load evidence remain rollout gates.

Part 2 depends on the Part 1 shell. Part 2.1 depends on the verified Part 2 organization context and
is the authorization prerequisite for the final Part 4/5/7 enforcement. Part 3 may proceed
independently at backend level but must use
the Part 1 console shell for its operator surfaces. Part 4 depends on Part 3 because presets replace
scenario types. Part 5 depends on Part 2 for document-manager authority but not on Part 3. Part 6
depends on Part 5 for retrieval evidence and on Part 3/4 for scenario evaluation. Part 7 depends on
Part 3 for the unified execution Run model. No later part may silently absorb another part's
acceptance gate.

## Locked product decisions

- “Tüm organizasyonlar” is removed. The last valid organization remains selected; otherwise the
  first authorized organization by deterministic `name`, `slug`, `pk` ordering becomes active.
- Active organization is navigation state, never an authorization input. Reads and writes always
  authorize the trusted target and tenant lineage server-side.
- Organization membership remains one role per user per organization. `document_manager` is a
  document-only role; it is not a combination of scenario or release roles.
- The target authorization model is defined by the
  [Part 2.1 scoped authorization and superadmin-recovery archive](archive/phase-2-8-part-2-1-scoped-authorization-superadmin-recovery-2026-07-24/plan.md).
  Daily Global Admin is an application role on a non-superuser account; Django superuser is a
  separate superadmin recovery identity. Delegated authority is organization-, project-,
  scenario- or document-set-scoped.
- Release/publish/rollback authority belongs only to Global Admin and the owning Organization
  Admin. Project Admin and Scenario Editor may prepare and test but cannot publish.
- There is no person-level `document_set_user` target role. A Document Set Manager grants a
  scenario `retrieve` authority over a document set; binding configures an already-authorized use.
  Administrative authority does not imply document-content or raw retrieval-context access.
- New project, document set and consumer forms do not accept organization input. New scenarios do
  not accept project input and are created only inside an authorized project.
- Scenario types are removed through Part 3, not merely hidden. RAG is a governed workflow preset
  and agent behavior is an `agent_loop` node inside `workflow_definition`.
- `/v1/responses` becomes the canonical execution API. `/v1/chat/completions` remains the default
  synchronous compatibility example. `/v1/query` and `/v1/invoke` are removed at the approved
  atomic cutover.
- Responses uses an external `resp_...` identifier distinct from the internal Run UUID. The Run UUID
  is returned through `X-AgentHub-Run-Id` and is the identifier accepted by run status/cancel APIs.
- Compiler mode analysis emits supported modes and stable reasons. Tool and `agent_loop` nodes may
  run synchronously when the complete graph is bounded, timeout-controlled and cannot pause; the
  runtime independently revalidates the compiler decision.
- Sync disconnect requests cooperative cancellation and never silently transfers execution to a
  background worker. Terminal state is immutable and late provider/worker results are discarded.
- The runtime cutover assumes no production data or protected external consumer contract. A data
  inventory, dry-run, migration review and separate apply approval are still mandatory before any
  destructive migration.
- AI authoring is enabled where an approved immutable model profile and provider are configured.
  It never bypasses validation, explicit user acceptance or audit.
- Optional document summaries are off by default. Enabling them pins model/profile provenance and
  makes failure visible; the system does not silently omit requested summary content.
- Index preparation may be automatic, but activation remains an explicit authorized action.

## Part records

- [Part 2 archive](archive/phase-2-8-part-2-organization-access-management-2026-07-22/plan.md)
- [Part 3 archive](archive/phase-2-8-part-3-unified-workflow-engine-2026-07-28/plan.md)
- [Part 4 plan](../tasks/phase-2-8-part-4-scenario-authoring-release-experience/plan.md)
- [Part 5 plan](../tasks/phase-2-8-part-5-document-profiles-index-automation/plan.md)
- [Part 6 plan](../tasks/phase-2-8-part-6-question-sets-evaluation/plan.md)
- [Part 7 plan](../tasks/phase-2-8-part-7-unified-runs-kill-switch/plan.md)

Each directory also contains its proportional `threat-model.md` and `verification.md`.

## Shared architecture and interface boundaries

- Exact artifact, release, index and model-profile versions remain pinned and checksummed. No UI
  simplification may introduce “latest” resolution, silent promotion or a second publish path.
- The unified workflow engine retains tenant, actor, authorization, capability, release, secret,
  budget and audit namespaces as server-owned state. DSL mappings cannot write them.
- `POST /v1/responses` supports explicit synchronous/background selection. Unsupported synchronous
  execution fails with `unsupported_execution_mode` and safe compiler reason codes; it never
  silently becomes background work.
- `POST /v1/chat/completions` remains synchronous and preserves its compatible response envelope.
  Both endpoints return the unified Run UUID through `X-AgentHub-Run-Id`; Responses uses a separate
  externally compatible `resp_...` response ID.
- `GET /v1/runs/{uuid}` and idempotent `POST /v1/runs/{uuid}/cancel` become the execution status and
  cancellation surfaces. Unified
  console presentation does not merge the distinct authorization rules of ingestion, evaluation or
  synchronization jobs.
- Part 3 requires an ADR for the single-engine decision, public API cutover, migration policy and
  rollback boundary before destructive cleanup.
- No new production dependency is approved by this phase plan.

## Security, authorization and tenant isolation

- Every part must test anonymous, membership-less, wrong-role, disabled-organization, forged-ID,
  revoked-membership and cross-tenant paths. UI hiding is never the access boundary.
- Organization selection can only narrow or align already-authorized context. Object detail views
  must authorize before rendering metadata or aligning the workspace.
- Membership/role changes, artifact publish, release actions, document lifecycle changes, summary
  generation requests, evaluation starts and kill-switch changes use stable, content-free audit
  events. Required audit failure rolls back security-sensitive state changes.
- PostgreSQL FORCE RLS remains a backstop for every new direct tenant table. Migrations include
  non-owner tests and reviewed grants/policies before verification.
- Global runtime suspension is platform-admin-only. Organization suspension is limited to platform
  admins and that organization's administrator. It is not a consumer capability.
- Destructive document cleanup and unified-runtime cleanup are separate approvals with explicit
  targets, inventory evidence, protected-reference checks and backup/rollback proof.

## Data, privacy and observability

- Questions, expected answers, generated answers, document text, chunks, summaries and model/judge
  inputs are tenant-confidential. They do not appear in application logs, audit payloads, trace
  attributes or metric labels.
- Run and evaluation persistence stores bounded redacted state, checksums, safe identifiers, status,
  counts and stable reason codes. Chain-of-thought is never stored or shown.
- LLM-derived summaries and judge results retain immutable model/profile, prompt/contract revision,
  content checksum and creation provenance.
- Retrieval diagnostics may display authorized chunk text in the console but persist only bounded
  evidence needed for reproducibility; raw content is never copied into logs or metrics.
- Operational filters use bounded parameters and low-cardinality metric dimensions. Cross-tenant
  totals are not exposed through the unified run read model.

## Migration and cutover policy

- Parts 2, 5 and 6 use additive/reversible schema changes until their own cleanup gate is approved.
- Part 3 uses staged gates for inventory/ADR, DSL/compiler parity, additive unified Run/Event state
  machine, consumer migration, destructive readiness, atomic removal and documentation closure.
  Mixed old/new compiled contracts or workers are not permitted at the atomic cutover.
- Before Part 3 cleanup, static references, fixtures, demo data, resumable runs, release manifests,
  API consumers and database row counts are inventoried and must prove there is no protected state or
  old API consumer. The migration applies only after manual approval of the exact diff and a tested
  previous-code plus empty-database recreation/migrate/seed rollback procedure.
- Part 5 initially denies new unbound documents. Existing unbound rows are reported by a dry-run
  tool; deletion is a separate confirmed operation that refuses published pins, retention/legal
  holds or incomplete object-store evidence.
- Current-behavior documentation changes only after the owning part is implemented and verified.

## Quality and UX principles

- Pages lead with the user's task and explain technical terms where they first appear.
- Empty states state what belongs there, why it may be empty and the next authorized action.
- Status uses text as well as color. Focus, keyboard operation, headings, responsive tables,
  reduced-motion and screen-reader semantics remain acceptance criteria.
- Technical provenance remains available as secondary detail: exact version, checksum, profile,
  index, release and run identifiers must not disappear from support/governance views.
- Retrieval and answer quality are reported separately. A single combined success percentage must
  not hide missing retrieval or judge errors.

## Phase acceptance criteria

- [x] Part 1 is implemented, verified, owner-accepted and archived.
- [ ] Parts 2–7 each have an approved plan and threat model before implementation.
- [ ] Every part records implementation and verification as separate states with repository-standard
      evidence.
- [ ] Organization context, create flows and role assignment are server-authoritative and pass
      denial/cross-tenant tests.
- [ ] RAG, workflow and agent execution use one verified workflow compiler/runtime/Run model with
      preserved RAG and agent safety invariants.
- [ ] Scenario, document, evaluation and operations experiences meet their task-specific acceptance
      criteria without exposing registry/runtime internals as primary navigation.
- [ ] Public API and destructive migrations receive their explicit acceptance gates and rollback
      evidence.
- [ ] Staff-engineer, AppSec and SRE final reviews record no unresolved critical/high finding.
- [ ] Master plan, ADRs, current-state docs and archived task evidence agree with the delivered state.

## Rollout and rollback

Parts roll out independently except for the declared dependencies. Parts 2, 4, 5, 6 and 7 retain
safe disable/fallback behavior without deleting tenant content. Part 3 is validated on a
staging-equivalent PostgreSQL/RLS environment and cuts over atomically; rollback is the previous
application version plus recreation of an empty database, previous migrations and approved
seed/configuration—not an in-place downgrade or mixed worker fleet. Runtime and document destructive
cleanup never shares a single approval.

## Principal risks

- Generalizing agent execution can weaken tool, approval, budget or prompt-injection defenses.
- Moving RAG into nodes can alter grounding, fallback, citation or ACL behavior.
- Sync and background paths can diverge unless they use the same transition services.
- Organization context can be mistaken for authority and cause IDOR/metadata disclosure.
- BM25/vector fusion can produce misleading scores unless component and fused scores are explicit.
- LLM summaries/judges can leak content or become irreproducible without pinned provenance.
- Unified run presentation can imply cancellation authority that the underlying job does not grant.
- Broad UX work can become unreviewable; part and internal gate boundaries are mandatory.

## Status and completion

**In progress.** Parts 1–3 are verified and owner-accepted. Parts 4–7 are implemented and
automated/offline verified; their explicit browser/live-provider/scale rollout gates and owner
acceptance remain.

Phase 2.8 completes only after all seven parts are implemented and verified, required ADRs and
current-state documentation are updated, destructive operations have their separate approvals and
evidence, residual risks receive owner acceptance, and completed task records are archived under the
planning policy.

## Production promotion gate

Before Phase 2.8 is promoted to production, the immutable deployment pipeline must build the
workflow-builder frontend with the pinned lockfile, run Django `collectstatic`, and publish
`STATIC_ROOT` at `STATIC_URL` through the deployment-owned web tier or CDN. Production must keep
`DEBUG=False`; Django's development static-file route is not an acceptable production fallback.

Staging-equivalent evidence must show that the authenticated builder page loads its generated
JavaScript and CSS with successful responses and correct content types, while a production-settings
URL resolution check confirms that Django does not expose the development static-file route. The
release must fail before promotion when the frontend bundle or collected static output is missing,
and rollback must restore the previous immutable application and matching static-asset set.
