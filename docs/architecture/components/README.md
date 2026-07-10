# Component Architecture Documents

Create `<component>.md` when a component exists. Describe verified current behavior rather than planned milestones. Include:

- purpose, ownership, and boundary;
- current behavior and invariants;
- inbound/outbound interfaces and compatibility;
- configuration and secret references (never values);
- data stores, classifications, and flows;
- authentication, authorization, tenant isolation, and other controls;
- dependencies, timeouts, retries, idempotency, and failure modes;
- logs, metrics, traces, audits, dashboards, and alerts;
- deployment, scaling, migrations, rollback, and operational notes;
- links to code, ADRs, runbooks, plans, and verification.

Label assumptions and gaps explicitly. Never document a target behavior as current.
