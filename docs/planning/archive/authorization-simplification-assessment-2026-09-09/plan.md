# Authorization simplification assessment

## Scope and status

Completed assessment, requested 2026-09-09. Preserve organization, project
and scenario boundaries. Inspect current working-tree behavior, human roles,
machine consumer capabilities, document grants, runtime/tool safeguards, and
browser presentation. Recommend a simpler product model; do not change authority,
application code, API contracts, dependencies, migrations or live data.

## Acceptance criteria

- Inventory roles and capabilities and verify their enforcement in source/tests.
- Distinguish UI affordances, human authority, machine authority and runtime policy.
- Explain which distinctions provide real isolation and which can become presets.
- Provide an explicit proposed role/permission mapping and migration risks.
- Record evidence and verification limits; archive the completed assessment and
  link it from the master plan without adopting the proposal as implementation.

## Steps and checks

1. Inspect instructions, existing ADRs, current diff and authorization entry points.
2. Trace identity assignments, document access, REST/MCP and frontend flags.
3. Run relevant existing isolated tests where the local test environment permits.
4. Write assessment, review evidence as architecture/security/operations, check
   documentation links and whitespace, and archive assessment records.

## Assumptions and risks

- Existing uncommitted edits belong to other work and must be preserved.
- Codebase Memory and Serena tools are unavailable in this session; exact searches,
  direct source inspection and tests provide evidence instead.
- Simpler role assignment must not silently widen cross-tenant/project/scenario
  access, expose source documents, enable side effects or remove human approvals.
- Any inheritance, role merge or consumer-capability removal is a proposal requiring
  a separately approved implementation; historical ADR approval is not current scope.
- Runtime/database state and actual customer separation-of-duties requirements are
  not inferred from historical handoff notes.

## Impacts

Documentation only. No runtime, authorization, privacy, telemetry, dependency,
schema, API or migration changes. No deployment or rollback is needed.

## Completion evidence

Assessment written and source inventory verified. Existing targeted backend tests:
43 passed; targeted frontend tests: 15 passed. Detailed limits and final document
checks are in [verification.md](verification.md). The proposed model is not
implemented, approved, or runtime-verified. No replacement implementation plan.
