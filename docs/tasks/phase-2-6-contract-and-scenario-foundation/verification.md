# Verification: phase-2-6-contract-and-scenario-foundation

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Task initialized | repository inspection | Pass | P2.6.0 plan and threat model created | Runtime implementation not started |
| Initial contract inventory | focused `rg` plus compiler/model/runtime inspection | Pass | `current-contract-inventory.md` | Remaining inventory explicitly listed |
| Documentation diff hygiene | scoped `git diff --check` over Phase 2.6 planning, ADR and P2.6.0 task paths | Pass | No whitespace errors | Unrelated global Git ignore permission warning only |
| UTF-8 replacement-character check | PowerShell UTF-8 read of P2.6.0 task files | Pass | No U+FFFD found | Four task files checked |
| Architecture proposals | manual contract review | Drafted | ADR-0008 and ADR-0009 | Owner/security/operations acceptance pending |
| Scenario corpus initialized | PowerShell JSON parse plus Python `jsonschema.validate` for all corpus entries | Pass | 7 scenarios, 13 required trajectories | Target files remain planning-only |
| Target fixture loader exclusion | `rg -n "scenario-corpus\.target\|target-scenario-contract" apps config` | Pass | Zero runtime/loader references | Files live only under the task record |
| Ownership and cutover matrix | repository seam review | Pass | `migration-and-ownership-matrix.md` | Role owners fixed; human names/numbers assigned at branch creation |
| Target workflow wrappers | Python JSON Schema plus node/edge reference assertions | Pass | 7 unique target workflows validated | Planning wrappers only |
| Current compiler exclusion | direct `compile_workflow` call for every wrapper | Pass | Current compiler rejected 7 of 7 | Prevents premature import/support claim |
| Owner architecture decisions | owner approval on 2026-07-16 | Pass | ADR-0008/0009/0010 Accepted; `decisions.md` | Later-part authorization gates preserved |
| Local documentation links | Python relative Markdown link existence check | Pass | 11 P2.6.0/ADR Markdown files checked | External URLs not dereferenced |

## Acceptance criteria mapping

1. Current grammar/compiler/runtime/persistence/fixture consumers: `current-contract-inventory.md`.
2. Durable transition and child authority: Accepted ADR-0008 and ADR-0009.
3. Scenario happy/denial/failure/recovery intent: `scenario-corpus.md` and seven target wrappers.
4. Atomic cutover consumers and reset safety: `migration-and-ownership-matrix.md`.
5. Role-based seam ownership, migration allocation and wave gates: matrix plus Phase 2.6 execution
   waves. Exact human names and migration numbers are assigned when branches are created from the
   merged baseline, avoiding stale allocations.
6. Target fixtures are inert: wrapper schema, task-only location, zero loader references and current
   compiler rejection evidence.
7. Owner decisions are recorded in `decisions.md`; ADR-0008/0009/0010 are Accepted. Later public
   API/authentication/network/production gates remain explicitly outside P2.6.0 authorization.

## Security requirement mapping

Trust boundaries, abuse/failure cases, mitigations and required negative tests are recorded in
`threat-model.md`. ADR-0008/0010 bind protected state, replay-safe resume, deterministic merge,
fail-closed required audit and non-production reset safety; ADR-0009 binds child attenuation.

## Authorization tests

Not run; this task has not changed executable behavior.

## Cross-tenant tests

Not run; cross-tenant scenario trajectories and later executable fixtures are pending.

## Logging and redaction tests

Not run; transition/audit vocabulary and executable behavior are pending.

## Audit event tests

Not run; no audit implementation changed.

## Migration verification

No migration created or applied. Migration inventory and allocation remain pending.

## Behavior comparison with base branch

No executable behavior is intended to change in this initialization step.

## Checks not run

Application formatter/linter/type/full tests, migrations, PostgreSQL/Celery recovery and runtime
security tests were not run because P2.6.0 changes only planning, ADR and inert JSON fixtures. Those
checks belong to the implementing parts. The project `.venv` executable was unavailable with a
Windows logon-session error; fixture and direct compiler checks succeeded with the available system
Python. A full Django startup attempt also lacked `opentelemetry` in that system environment, so no
claim of a full application check is made.

## Remaining risks

The worktree contains unrelated uncommitted changes. The first parallel wave is not open until the
P2.6.0 files are isolated into a reviewed commit and merged as the integration baseline. Exact
human owners and migration numbers must be assigned at branch creation. Runtime proof remains the
responsibility of P2.6.1 onward.

## Human review required

Before opening branches, manually review the isolated P2.6.0 diff and assign the integration owner,
feature owners and migration ranges. Public event ingress/authentication, database reset, live MCP
egress and Python runner activation still require their later explicit approvals.

## Final status

Completed. Documentation/fixture foundation is verified; committed/merged integration baseline is
the next delivery action.
