# Threat Model: Scenario Studio JSON and graph authoring completion

## Assets and trust boundaries

The browser supplies untrusted JSON/graph state across the authenticated console boundary. Mutable
scenario drafts, immutable workflow artifacts, release pins, tenant/scenario lineage and audit
evidence are protected assets. Browser query parameters and JSON fields are never authority.

## Primary threats

- Forged organization/project/scenario/draft identifiers cross tenant or scenario boundaries.
- Oversized, deeply nested, malformed or secret-bearing JSON exhausts services or leaks data.
- A JSON candidate is rendered one way but a different graph body is saved or published.
- Copying an active workflow mutates or appears to mutate the immutable artifact/release.
- AI candidate acceptance drops scenario lineage and creates an unrelated draft.
- Concurrent tabs silently overwrite a newer draft.
- Diagnostics echo raw bodies, prompts, secrets or internal exceptions.

## Mitigations

- Resolve scenario, project and active workflow only through authenticated server-side scope and
  recheck their organization relationship on every mutation.
- Reuse the existing bounded JSON parser, draft body limits, inline-secret policy and canonical
  workflow compiler. Apply JSON to graph only after successful backend diagnostics.
- Treat graph and JSON as views of one in-memory candidate; save/publish serialize that candidate
  and require the current revision.
- Copy immutable workflow bodies into a new mutable scenario-linked draft only after an explicit
  author action. Never update an `ArtifactVersion` or release from Studio editing.
- Return stable content-free error codes; do not log or audit bodies.
- Keep authoring permission, CSRF and tenant isolation enforcement server-side.

## Required negative tests

Unauthenticated and auditor mutation denial; cross-tenant/foreign scenario/project/draft denial;
active artifact type/checksum mismatch; malformed/non-object/oversized/deep/secret-like JSON;
compiler-invalid workflow; immutable artifact/release non-mutation; stale revision preservation;
safe diagnostics and AI acceptance with exact scenario lineage.

## Residual risks

Automatic graph layout is presentation state and is not stored in the workflow DSL. Complex graphs
may need later layout controls, but this must not change canonical body or checksum semantics.

