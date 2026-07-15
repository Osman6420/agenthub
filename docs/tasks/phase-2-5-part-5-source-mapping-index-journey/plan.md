# Task Plan: phase-2-5-part-5-source-mapping-index-journey

## Task summary
Unify the existing governed connector, mapping, sync, draft, staged-index and active-index capabilities into one document-set-scoped Turkish journey.

## Background
Phase 2.5 Part 5 maps to P2.5.4. The backend already separates platform profiles, immutable REST mapping contracts and tenant source instances, and already enforces bounded preview, sync and promotion gates. The console currently exposes these controls but does not present a coherent wizard or end-to-end operational state.

## Scope
- Rework the set-scoped connector workspace into a source wizard with explicit safe steps.
- Add source detail navigation and safe operational status, run counts, draft/index state and next actions.
- Cross-link source, document set, scenario and index/release consumers where authorized.
- Preserve redaction of endpoints, credentials, connector inputs and document content.
- Add authorization, tenant-isolation, redaction and status-projection tests.
- Update architecture, manual testing and Phase 2.5 planning evidence.

## Non-goals
- New connector types, network policies, parser formats or production dependencies.
- Automatic activation outside the existing approved schedule/promotion gates.
- Changing public API contracts or persistence schemas unless implementation proves it necessary.

## Acceptance criteria
- An authorized author can follow profile → mapping → validation → binding → sync from one set-scoped workspace.
- A source detail page shows health, last sync, safe failure code, counts, draft/published/index progression and authorized next action.
- Secrets, endpoint details, operator inputs and content never render.
- Auditors have read-only access; unauthorized and cross-tenant access fail closed.
- Sync never changes the active index directly.

## Affected components
Console views, URLs, forms/templates, ingestion/document projections, console tests and product documentation.

## Interfaces affected
Additive authenticated console routes only.

## Data impact
Read-only projections over existing source, sync run, document-set version and index-version records. Existing create/run/schedule operations remain authoritative.

## Security impact
The UI crosses platform-profile, tenant-source, synthetic sample and operational-status boundaries. All rendered fields use explicit safe projections.

## Authorization impact
Existing tenant scoping and scenario-author/release-manager policy remain authoritative. Read-only auditor access is preserved; mutations remain server-side authorized.

## Observability impact
Existing audit events and safe sync failure codes remain unchanged. The console surfaces existing safe operational evidence without exposing raw errors.

## Migration impact
None expected.

## Dependencies
P2.5 Part 4 document-set lifecycle and the existing governed connector/index services.

## Implementation steps
1. Inventory source/run/index symbols and confirm trust boundaries.
2. Add safe lifecycle projection and source detail route.
3. Restructure the connector workspace as a guided source wizard.
4. Add focused security, authorization and compatibility tests.
5. Run focused and repository verification, update evidence and plans.

## Test plan
Cover happy path, auditor read-only, unauthenticated/unauthorized and cross-tenant denial, endpoint/secret/input/content redaction, bounded preview without egress, safe failure projection, lifecycle/index projection, and existing schedule/promotion controls.

## Rollout plan
Additive console rollout; restart local web/worker only after automated verification.

## Rollback plan
Revert the additive routes/templates/projections; existing connector services remain intact.

## Risks
- Accidental disclosure through model rendering or raw connector/run fields.
- Misleading index state due to a non-tenant-scoped or non-set-scoped query.
- UI implying sync directly activates an index.

## Open questions
Authenticated Turkish owner browser acceptance remains a manual gate.

## Status
Verified. Authenticated Turkish owner browser review remains before Completed.

## Completion criteria
Implementation and security tests pass on SQLite and PostgreSQL; static, migration and final-diff checks pass; evidence is recorded; authenticated Turkish owner review is reported separately.
