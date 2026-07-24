# Task Plan: ragflow-capability-delegation-assessment

## Task summary
Build a CSV inventory of AgentHub capabilities from all phase plans and verification records, including unfinished work, and assess which capabilities could be delegated to open-source RAGFlow.

## Background
The assessment must distinguish planned, implemented, and verified behavior. It must estimate removable AgentHub code and required RAGFlow integration code without presenting estimates as measured facts.

## Scope
- Review master, phase, component, active task, and archived task plans.
- Review corresponding verification and runtime-verification records.
- Reconcile documented status with relevant source-code footprint where needed.
- Research current open-source RAGFlow capabilities from official sources.
- Produce one CSV row per normalized project capability.
- Include unfinished planned capabilities.
- Estimate gross removable code, new integration code, and net code reduction.

## Non-goals
- Implement RAGFlow integration.
- Change product architecture, dependencies, authorization, or production configuration.
- Claim exact deletion counts before a concrete migration design and diff exist.

## Acceptance criteria
- CSV is valid UTF-8 and parses successfully.
- Each row identifies project area, capability, lifecycle status, and evidence sources.
- Each row records RAGFlow delegation fit and rationale.
- Code estimates include confidence and estimation basis.
- Planned but unfinished capabilities are present.
- Security, authorization, tenancy, audit, and operational boundaries are not assumed delegable merely because RAGFlow has adjacent functionality.

## Affected components
- Documentation only.
- New analysis artifact under `docs/analysis/`.

## Interfaces affected
None.

## Data impact
None. Repository metadata and source text are read locally; no production or user data is accessed.

## Security impact
The report may influence a future trust-boundary change. It must explicitly flag identity, tenant isolation, authorization, credential storage, audit, and data-egress concerns.

## Authorization impact
No current behavior changes. Delegation recommendations must preserve AgentHub as the policy enforcement point unless official evidence supports an equivalent control.

## Observability impact
No current behavior changes. Recommendations must account for tracing, audit correlation, retry visibility, and operational ownership.

## Migration impact
No database migration. Future migration complexity is assessed qualitatively in the CSV.

## Dependencies
- Repository plans, verification records, source tree, and git metadata.
- Official RAGFlow documentation and official GitHub repository.

## Implementation steps
1. Inventory authoritative planning and verification sources.
2. Normalize capabilities and lifecycle states.
3. Map capability areas to current code footprint.
4. Research RAGFlow support and integration APIs from official sources.
5. Estimate gross removal, integration addition, and net reduction with confidence.
6. Generate and parse-validate the CSV.
7. Review findings from architecture, application-security, and SRE perspectives.

## Test plan
- Parse CSV using the Python standard library.
- Assert required columns, unique row identifiers, numeric estimate fields, and valid enum values.
- Sample-check plan/verification evidence paths.
- Reconcile estimate totals and verify no negative arithmetic errors.

## Rollout plan
Deliver the CSV as a documentation artifact. No runtime rollout.

## Rollback plan
Remove the documentation artifact and task records if the assessment is rejected.

## Risks
- Plans may be stale or superseded.
- Verification records vary in completeness.
- One capability can span multiple modules, making line attribution approximate.
- RAGFlow features and APIs may change.
- Gross removable lines are not equivalent to safe deletion without contract, data, and control-plane migration work.

## Open questions
- Exact deployment topology, RAGFlow version, and operational ownership are not yet selected.
- Estimates assume self-hosted open-source RAGFlow and an API-based integration.

## Status
Verified. The documentation artifact is complete and machine-validated. Human architecture and
security review remains required before any recommendation becomes an implementation decision.

## Completion criteria
The CSV, verification record, source citations, estimate methodology, and final multidisciplinary review are complete.
