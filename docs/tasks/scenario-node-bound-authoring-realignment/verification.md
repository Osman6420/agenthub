# Verification: scenario-node-bound-authoring-realignment

## Part 8A — document-set authority correction

### Automated evidence

- `pytest apps/console/tests/test_document_workspace_console.py -q`: 8 passed.
- The matched authorization test proves an exact Document Set Manager with no scenario binding can
  inspect, create and version preparation artifacts, while a bound Scenario Editor with only
  document-set metadata visibility receives HTTP 403 and creates no version.
- The same test rejects a foreign-tenant source artifact without disclosure, proves immutable N+1
  publication and records safe success/denial audit events.
- Ruff format/check passed for the changed Python files. Mypy passed for the new document profile
  authoring service and console views. Django system check, JavaScript syntax and diff whitespace
  checks passed.

### Live/runtime evidence

- Canonical Compose inspection showed PostgreSQL, Redis, MinIO, web, all three worker roles and beat
  running; `/v1/health/live` returned HTTP 200 after a controlled web-only restart.
- The live document-set page displayed new inline artifact cards. Opening the selected chunking
  profile showed editable content, required exact-version description and immutable publish action.
- The obsolete bound-scenario author message was absent. No live artifact version was published.

### Security and operational review

- Server authorization uses exact `DOCUMENT_SET_OPERATIONS_MANAGE` against the requested set. A
  scenario assignment is never consulted and cannot grant this operation.
- Source artifacts are re-resolved by exact organization and allowlisted type. Request bodies are
  bounded, canonical validators run before persistence, active model-profile references are checked,
  and endpoint/secret-bearing platform fields are never accepted or projected.
- Artifact creation and success audit share one transaction. Denials are audited separately without
  artifact body, prompt text, profile endpoint or secret data.

### Residual items

- Retrieval still appears in document-set preparation during the compatibility period. Moving its
  primary ownership into Retrieve-node DSL/runtime remains Part 8D.
- The retained same-origin cross-tab notification is compatibility-only now that document-owned
  primary editing is inline; later cleanup may remove it after node-bound migration.
