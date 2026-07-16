# P2.6.0 Owner Decisions

Accepted by the project owner on 2026-07-16 after review of the proposed defaults:

1. State references use a restricted absolute JSON Pointer subset.
2. Initial join modes are `all`, `threshold` and `fail_fast`.
3. Branches own separate result namespaces; joins use explicit ordered mappings and reject target
   conflicts. There is no implicit last-writer-wins behavior.
4. Initial generic event resume uses authenticated HTTP plus an opaque one-time correlation secret;
   only its hash is stored.
5. Human decisions use a distinct typed `human_task` primitive while sharing the established
   approval security invariants.
6. Required audit evidence for security/business decisions is fail-closed and transactionally bound
   to the state change. Optional logs, metrics and traces are fail-open.
7. Dummy workflow data may be reset only through a separately confirmed, identity-checked procedure
   against an explicitly named local/development/test database.
8. ADR-0008 and ADR-0009 are accepted. ADR-0010 records the accepted supporting grammar decisions.
9. `agenthub/v1` evolves in place; multi-agent supervision remains Phase 3.

These decisions authorize P2.6.0 contract closure. They do not authorize implementation-time public
API/authentication changes, a database reset, live event/MCP egress or production activation; those
retain the explicit gates in `AGENTS.md` and the owning task plans.
