# Threat Model: P2.6.7 governed MCP catalog synchronization

## Assets, actors, and trust boundaries

- Assets: tenant identity, approved source destination, secret reference, remote catalog metadata,
  quarantined candidate checksums, immutable tool definitions, releases/bindings, audit trail.
- Actors: platform/operator service configuring approved sources; tenant-scoped reviewer; untrusted
  remote MCP server; existing runtime proxy.
- Boundaries: database tenant scope; secret resolver; DNS and outbound TLS; untrusted JSON-RPC and
  JSON Schema; quarantine-to-registry review; registry-to-release runtime resolution.

## Threats and controls

| Threat | Control | Evidence |
| --- | --- | --- |
| Discovery widens authority | Discovery only writes candidates; review creates a definition, never a binding/release/grant | negative tests |
| Cross-tenant read/review | organization required in every service query; direct tenant column/RLS inventory | SQLite + PostgreSQL tests |
| Endpoint/token disclosure | no UI/API; ephemeral credential; audit contains IDs/reason only | audit redaction tests |
| SSRF/DNS rebinding | destination shape plus fresh DNS validation; client receives pinned addresses | resolver tests |
| Redirect | shared bounded HTTPS transport rejects every 3xx | adapter regression |
| Catalog/schema/name explosion | hard item/body/schema-node/depth/name limits, exact keys, duplicate denial | malicious catalog tests |
| Schema parser abuse | data-only bounded traversal then `jsonschema` schema validation; no refs resolved or code evaluated | schema tests |
| Drift/disappearance | new candidate remains quarantined; prior registered candidate marked drifted/missing; immutable definition unchanged | drift tests |
| Stale review/TOCTOU | row lock and exact candidate checksum; source/candidate tenant match; atomic artifact registration | stale review test |
| Audit outage | security-sensitive discovery/review transaction is atomic; audit failure rolls back | failure test |

## Residual risks and operational controls

- Production private MCP egress, CA, firewall and credentials are deployment-owned and unverified;
  this closure performs no live call and does not alter network policy.
- Source provisioning remains an internal service boundary; adding a UI/public API requires explicit
  authorization and contract approval.
- JSON Schema validation proves structure, not remote tool honesty. Risk, side effects, redaction,
  approval, contracts and destination remain explicit reviewer decisions.
- Disabling a source prevents new discovery but does not revoke already pinned releases; existing
  definition/binding kill switches remain the operational revocation mechanism.
- **Activation blocker:** `deploy/postgres/provision-app-role.sql` does not grant the new protected
  tables. Migration-local FORCE RLS exists, but production app-role access cannot be activated until
  an owner explicitly approves the production authorization change and the non-owner RLS proof.
