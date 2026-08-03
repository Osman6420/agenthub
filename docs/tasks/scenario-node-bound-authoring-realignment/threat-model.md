# Threat Model: scenario-node-bound-authoring-realignment

## Assets and trust boundaries

- Exact workflow node identities, artifact roles/versions/checksums, scenario defaults and candidate
  manifests.
- Tenant document-set/index provenance and platform profile identifiers.
- Provider endpoints, secret references, live release pointers and traffic state.
- Browser-to-server authoring, mutable-to-immutable publication, compiler-to-runtime resolution and
  candidate-to-live authorization boundaries.

## Primary threats

- Forge a node role or artifact ID to resolve a foreign, wrong-type, inactive or unpinned artifact.
- Rename/copy nodes to collide with another node's prompt/model/retrieval role.
- Treat missing and invalid explicit bindings alike and silently fall back to a default.
- Use Scenario Editor candidate authority to promote, activate, canary or otherwise affect traffic.
- Use authority over one bound scenario to create/version profiles for a shared document set, or use
  authority over one document set to mutate another set's selected artifact lineage.
- Leak model/embedding/OCR endpoint or secret fields through inline selectors or diagnostics.
- Migrate retrieval ownership in a way that changes an active release/index without explicit publish
  and promotion.

## Required controls and evidence

- Server-generated stable roles; exact type/tenant/checksum pinning; canonical body validation;
  explicit-binding failure is deny-closed.
- Matched Scenario Editor/Release Manager allow-deny tests for candidate and every live transition,
  including direct POST and cross-tenant probes.
- Matched Document Set Manager/scenario-only editor/viewer tests: only the exact set manager may
  create/version its preparation artifacts, regardless of how many scenarios bind the set.
- Safe profile serializers with endpoint/secret negative assertions and no content-bearing audit.
- Compiler-version/checkpoint compatibility tests plus legacy release/index replay evidence.
- Additive migration, preserved historical provenance, prior-active-state rollback and browser tests
  for two Generate and two Retrieve nodes.

## Residual risk

Automatic defaults and compatibility fallback reduce visible configuration. The UI must always show
which exact default or override will be pinned, and compatibility fallback must be removed only after
all active legacy workflow versions are inventoried or migrated.
