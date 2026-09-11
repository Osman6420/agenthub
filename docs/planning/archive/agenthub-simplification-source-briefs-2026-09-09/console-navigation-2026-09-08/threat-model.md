# Navigation threat model

Assets: scenario names/metadata, organization/project membership and object scope;
existing server-authorized mutations and audit continuity.

Trust boundaries: session selects a membership-validated display scope; query strings
are untrusted filters; server scoping remains authoritative. Scenario names and search
text must stay template-escaped. Pagination/filter links must encode text. Sidebar
visibility never grants access. Creation retains trusted project URL context and exact
SCENARIO_CREATE checks. No client-controlled return URL or authentication shortcut.

Mitigations: reuse scoped_scenarios/scoped_projects, narrow to active organization,
bound result pages/search inputs, validate project UUID filters, apply existing
permission functions to action affordances. Do not change authorization definitions.
Test anonymous, unassigned, same-organization foreign scope, other organization and
stale/invalid filters. Preserve existing denial/audit tests and explicit publish actions.

Operational risk: shared navigation touches many screens. Inventory every template,
test route-family mapping, verify live links/fragment targets and responsive layout.
No workers, model providers, database schema or stored documents should change.
