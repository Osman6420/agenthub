# Threat Model: phase-2-5-part-6-scenario-studio

## Assets
Mutable workflow/artifact drafts, immutable artifact bodies and checksums, scenario/project lineage,
release manifests, active runtime pins, document-set/consumer bindings, prompt/model/tool/retrieval
configuration and audit evidence.

## Actors
Organization/project owners, scenario authors, release managers, auditors, platform administrators,
unauthenticated users and authenticated users from another tenant.

## Entry points
Scenario Studio HTML/JSON routes, builder deep links and draft APIs, diagnostics/publish actions,
artifact compatibility queries/selectors and existing release compile/evaluate/promote actions.

## Trust boundaries
Browser graph/JSON→Django; scenario→project/organization; mutable draft→canonical validator/compiler;
organization artifact inventory→role-compatible selection; selected refs→release compiler; candidate
release→evaluation/promotion; operator content→logs/audit/UI diagnostics.

## Data classifications
Draft/artifact bodies, prompts, document content, tool endpoints and credentials are restricted.
Checksums, logical IDs, versions, statuses and safe diagnostics are internal metadata. Active release
and authorization decisions are security-sensitive control state.

## Authentication
All Studio routes require authenticated Django sessions. Mutations require POST/JSON methods, CSRF
and existing session controls.

## Authorization
Membership scopes reads. `can_author_scenarios` gates draft changes and immutable publication.
Existing release-manager policy gates release compilation/evaluation/promotion. The service layer
rechecks authorization against the resolved scenario/organization; client-supplied organization,
project, draft, artifact or release IDs are never authority.

## Tenant isolation
Resolve drafts and compatible artifact versions through the authorized scenario's organization.
Reject cross-organization scenario/project/draft associations and artifact pins with non-leaking
404/denial behavior. Any new persistence requires direct tenant lineage, constraints and FORCE RLS.

## External systems
None added. Model/tool/connector endpoints remain referenced through existing governed profiles and
must not be expanded or exposed by Studio projections.

## Abuse cases
- Forge a foreign draft/artifact/release ID through a selector or deep link.
- Pin an incompatible artifact type under a trusted manifest role.
- Modify a reusable immutable artifact through an editing surface.
- Submit oversized/deep/malformed JSON, inline secrets or injection-like labels.
- Use graph serialization differences to validate one body and publish another.
- Race draft updates or reuse a stale checksum to overwrite newer author work.
- Infer restricted content from diagnostics, list counts, checksum existence or raw exceptions.
- Make draft publication or selection appear to be active promotion.

## Failure cases
Compiler/validator rejection, missing/stale artifact version, checksum mismatch, deleted/missing draft,
concurrent update, release compile failure, audit persistence failure and a candidate release that
never evaluates or promotes.

## Logging and audit risks
Raw JSON, prompts, compiler exceptions or tool/credential fields could leak through diagnostics or
events. Events must use stable safe codes and references only. Required audited writes retain
fail-closed transactional behavior.

## Mitigations
Canonical server validation/serialization, body/depth bounds, inline-secret rejection, explicit
safe diagnostic mapping, same-organization queries, server-owned role/type allowlists, exact version
and checksum revalidation, immutable artifact services, separate author/release permissions, POST+
CSRF, atomic expected-revision checks across every mutable Studio aggregate, explicit lifecycle
labels and no automatic publish/compile/promote action. A stale update returns a stable conflict,
does not mutate stored state and never echoes the stored or submitted body into logs/audit metadata.

## Residual risks
The exact revision representation and browser reconciliation experience require implementation-time
design, but last-write-wins is not an accepted outcome. Authenticated Turkish owner visual
acceptance and complex real workflow author experience remain manual.

## Required security tests
Unauthenticated denial; auditor/role mutation denial; CSRF; forged and cross-tenant scenario/project/
draft/artifact/release IDs; role/type mismatch; checksum mismatch; immutable non-mutation; oversized/
deep/secret-like bodies; safe diagnostic redaction; two-editor current/stale revision behavior;
conflict redaction; audit failure rollback; candidate-versus-active lifecycle separation;
PostgreSQL FORCE RLS coverage for any new table/query path.
