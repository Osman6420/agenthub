# Component Plans

Create `docs/planning/components/<component>-plan.md` for an independently deliverable component, meaningful internal milestones, a security boundary, external integration, migration, separate operational lifecycle, work spanning multiple tasks, or a foundational service used by other components. Do not create one for a utility, single endpoint, or simple bug fix.

Component plans describe intended work; current behavior belongs in architecture/component docs. Update the master plan with real links only after files exist.

## Template

Copy this skeleton to a new component plan:

```md
# <Component> Plan

## Objective
## Owner or responsible area
## Status
## Scope
## Non-goals
## Current state
## Target state
## Interfaces
## Data flows
## Security boundaries
## Dependencies
## Milestones
## Risks
## Open decisions
## Testing strategy
## Observability requirements
## Rollout
## Rollback
## Completion criteria
## Links
```
