# AgentHub — Phase 2.8 Plan (PLANNED)

> **Status: In progress.** Part 1 was verified and owner-accepted on 2026-07-22; Parts 2–5 remain
> planned. Phase 2.8 turns the operator console into an organization-scoped,
> task-oriented product experience. It is a phase/program plan rather than a component plan:
> each part has an independent task record, threat model, verification evidence and acceptance
> gate. Planned behavior must not be presented as current until its part is implemented and
> verified.

## Purpose

The current console exposes backend entity categories and operational subtypes as primary
navigation. Users must understand artifacts, releases, agent/workflow run distinctions and the
organization/project/scenario ownership graph before they can complete ordinary tasks. Phase 2.8
reorganizes the experience around the user's working context, then adds governed authoring,
document-quality and operations capabilities in separately reviewable increments.

The target information hierarchy is:

`Organization → Project → Scenario`

Document sets remain organization-owned reusable resources related to scenarios; they are not
project children. Artifact versions and releases remain immutable governed implementation objects,
but are selected and inspected from their scenario context instead of acting as primary navigation.

## Delivery model

Each part must produce independently usable and testable software. Later parts reuse the navigation
and page shell delivered by Part 1, but Parts 2–5 do not depend on one another's completion. A part
may start only after its own scope, authorization effects, data changes and threat model are
approved.

1. **Part 1 — Console information architecture and UX foundation.** Task-oriented navigation,
   organization/project/scenario hierarchy, contextual legacy-list redirects, summary + task-tab
   detail pages, persistent sidebar, user chrome, explanatory copy and accessibility baselines.
2. **Part 2 — Scenario authoring, reusable artifacts and release experience.** Capability-oriented
   scenario creation; type → logical artifact → exact version selection; contextual drafts, graph,
   release history and OpenAI-compatible `curl` guidance.
3. **Part 3 — Document profiles, document manager and index automation.** Governed chunking and
   keyword/vector/hybrid retrieval controls; optional LLM-derived summaries; document-manager
   authorization; automatic index preparation followed by explicit activation. Every managed
   document must belong to at least one document set: prevent new unbound documents and define a
   separately approved, audited cleanup/migration for existing unbound database records. Cleanup
   must preserve retention/legal-hold and immutable published-version references; no destructive
   deletion is authorized by this phase plan alone.
4. **Part 4 — Question sets and retrieval/answer evaluation.** Organization-owned reusable question
   sets, document-set retrieval diagnostics, scenario answer evaluation, deterministic rules plus
   optional pinned LLM judge, and separate retrieval/answer quality reporting.
5. **Part 5 — Unified runs and kill-switch management.** A filterable operational read model across
   scenario, evaluation, ingestion and synchronization work; contextual decisions; organization and
   global runtime suspension controls with explicit authorization and audit.

## Cross-part product principles

- The organization selector is a convenience filter, never an authorization input. Every read and
  mutation remains server-scoped to allowed organizations and the trusted target object.
- Navigation follows user tasks. Technical runtime and registry identities remain available as
  secondary diagnostics where required for governance or support.
- Empty states explain what belongs in the area, why it can be empty and the authorized next action.
- Status is communicated with text in addition to color. Keyboard, focus, responsive-table and
  screen-reader semantics remain part of acceptance.
- Immutable release/artifact/index provenance is preserved. UI simplification must not introduce
  moving references, silent promotion or alternate publishing paths.
- Existing public gateway contracts and canonical state-changing routes remain compatible unless a
  later part explicitly obtains public-contract approval.

## Shared change boundaries

Part 1 is presentation/navigation only: no migration, production dependency, new role, public API
change or new mutation authority. Parts 2–5 must independently stop for approval before changing
authentication, authorization, tenant isolation, a public API contract, a production dependency,
or an irreversible migration.

In particular:

- Part 2 may change console authoring interfaces but must continue exact release pinning and current
  compiler/validator authority.
- Part 3 adds an organization role and document/index lifecycle behavior, so it requires a dedicated
  authorization matrix, migration review and denial/cross-tenant tests. Its unbound-document
  cleanup requires an inventory/dry-run, explicit deletion approval, audit evidence and rollback or
  backup proof before any database record or object-storage byte is removed.
- Part 4 persists questions, expected answers and evaluation evidence, so it requires explicit data
  classification, retention, redaction and model-judge provenance decisions.
- Part 5 exposes operational control. Organization-scoped and global kill-switch authority, audit
  failure behavior and in-flight run semantics require explicit approval before implementation.

## Data, privacy and observability

- Part 1 adds no stored data. Later parts use additive, reversible migrations unless separately
  approved.
- Questions, expected answers, generated answers, document text, chunks and LLM summaries are
  tenant-confidential content. They must not appear in application logs, audit payloads or metric
  labels.
- State changes retain stable actor, action, target, authorization decision, outcome, reason and
  trace correlation. Page views do not create business-audit events.
- Unified operational views use bounded, low-cardinality filters and safe identifiers; they do not
  merge authorization domains or expose cross-tenant counts.

## Dependencies

- Verified Phase 2/2.5 document, scenario, artifact, release and console behavior.
- Phase 2.6 workflow/agent runtime and operational state models.
- Current server-side organization scoping, PostgreSQL RLS verification and role predicates.
- Part 1 navigation/page-shell behavior for the presentation of Parts 2–5.

No new production dependency is approved by this phase plan.

## Phase acceptance criteria

- [ ] Every part has an approved task plan and proportional threat model before implementation.
- [ ] Each part tracks `Implemented` and `Verified` separately with repository-standard evidence.
- [ ] The console presents organization → project → scenario consistently; document sets remain
      organization-owned reusable resources.
- [ ] Artifact, release and runtime internals remain governed even when removed from primary
      navigation.
- [ ] Authorization denial, cross-tenant access, audit, redaction, compatibility and rollback tests
      pass for every applicable part.
- [ ] Current-state documentation changes only after behavior is verified.
- [ ] The master plan and this phase plan reflect the status of each part without overstating future
      behavior.

## Rollout and rollback

Each part rolls out independently through the normal non-production path. Presentation changes keep
canonical detail and action routes available until compatibility evidence permits removal. Additive
data models and roles from later parts must include downgrade/disable behavior and must not require
deleting tenant data to roll back application behavior.

## Risks

- A broad UX program can become one unreviewable release; independent part gates are mandatory.
- Hiding technical object types can obscure governance state; contextual pages must retain exact
  version, provenance and status diagnostics.
- Active-organization state can be mistaken for authorization and cause IDOR or metadata leakage.
- Automatic document processing can be confused with publishing or activation; later plans must
  name every lifecycle boundary explicitly.
- A single combined success percentage can hide retrieval or answer failure; Part 4 reports them
  separately.
- Unified run presentation can imply unified cancellation or control authority; Part 5 must retain
  type-specific authorization and lifecycle semantics.

## Status

**In progress.** Part 1 is verified and owner-accepted in
[`phase-2-8-part-1-console-information-architecture`](archive/phase-2-8-part-1-console-information-architecture-2026-07-22/plan.md).
Parts 2–5 require their own task records and approval before implementation.

## Completion criteria

Phase 2.8 is complete only when all five parts are implemented and verified, applicable current-state
documentation and ADRs are updated, final staff-engineer/AppSec/SRE reviews record no unresolved
critical or high finding, residual risks receive owner acceptance, and every completed task record is
archived according to the planning policy.
