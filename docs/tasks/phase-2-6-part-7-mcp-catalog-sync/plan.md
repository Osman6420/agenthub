# Task Plan: P2.6.7 governed MCP catalog synchronization activation closure

## Objective

Make MCP `tools/list` discovery activation-ready without granting runtime authority. Approved,
tenant-owned sources produce bounded quarantined candidates; an explicit review binds an exact
candidate checksum to a new immutable tool definition. Runtime remains release-pinned through the
existing tool proxy.

## Baseline and discovered gap

- Branch starts at `7f18a26`; `docs/planning/phase-2-6-plan.md` is integration-owner-owned and excluded.
- The baseline claims P2.6.7 is present, but contains no catalog source/candidate model, service,
  migration, task record, or test. The similarly named parallel branch has no commits after its
  merge base, so there is no implementation to merge.
- Existing `apps.tools` registry, artifact validation, SSRF-safe DNS/IP pinning, redirect-free HTTPS,
  secret resolver, approval policy, audit service, and exact release-pin proxy are reused unchanged.

## Scope

1. Add additive tenant-owned source and immutable candidate/snapshot records with quarantined,
   registered, drifted, missing, and rejected states.
2. Discover bounded `tools/list` metadata through an injectable client after destination DNS/IP
   validation; validate names and JSON Schemas under byte/count/depth budgets.
3. Detect changed and disappearing tools fail-closed and audit only safe IDs/reason codes.
4. Require explicit exact-checksum review plus a complete governed tool-definition manifest before
   calling the existing immutable artifact/registry services.
5. Add deterministic SQLite and PostgreSQL/RLS/security tests and operational documentation.

## Exclusions and approval gates

- No tenant UI, public API, live egress, dependency, production network/configuration, release,
  binding, capability, authentication, or authorization-contract change.
- No automatic activation, binding, grant, release mutation, or tool invocation.
- Production credentials/endpoints and live MCP systems are not exercised.
- Any need for the excluded changes above is a blocker requiring owner approval.

## Acceptance criteria

1. Discovery validates the source destination on every run and rejects DNS rebinding, redirects,
   malformed envelopes, malicious names/schemas, duplicate names, and catalog/size/depth explosion.
2. Every accepted item is quarantined. No ToolDefinition, ToolBinding, artifact, release, or grant is
   created by discovery.
3. Review is tenant-scoped, stale-checksum-safe, and registers exactly one immutable definition only
   after validating that its MCP name and input schema match the candidate.
4. Drift and disappearance create safe audited state and never mutate or disable the old pinned
   definition; runtime resolution continues to require the exact pinned checksum.
5. Audit records contain source/candidate IDs and stable reason codes, never endpoint, token, secret
   reference, schema, or raw catalog payload.
6. SQLite, PostgreSQL/RLS, focused negative tests, full regression, Ruff, format, mypy, Django check,
   migration drift, and final diff reviews are recorded.

## Implementation status

Implemented, but activation closure is blocked. The production application-role provisioning SQL
must grant the two new protected tables and the repository RLS inventory test requires that change.
Changing production authorization needs explicit owner approval under `AGENTS.md`; it was not made.
All non-blocked checks and the exact failing gate are recorded in `verification.md`.
