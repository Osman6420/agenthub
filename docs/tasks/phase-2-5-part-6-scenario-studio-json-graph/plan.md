# Task Plan: Scenario Studio JSON and graph authoring completion

## Task summary

Complete the missing Part 6 owner journey so every scenario opens an isolated Studio where a new
or existing workflow can be viewed and edited as either canonical JSON or a graph.

## Scope

- Show the selected scenario and project as locked Studio context.
- Keep scenario workflows isolated on their own pages; do not aggregate unrelated scenarios.
- Let a new scenario start from pasted workflow JSON or an empty graph.
- Load an existing scenario draft, or safely seed a new mutable draft from its exact active
  immutable `workflow_definition`, and render it in both JSON and graph views.
- Make JSON and graph two views of one candidate body. JSON application must parse, bound and run
  canonical backend diagnostics before it replaces graph state.
- Preserve optimistic revision checks, explicit save/publish and candidate-versus-active separation.
- Pass scenario/project context through AI candidate acceptance.

## Non-goals

- Mutating an existing artifact or active release.
- Automatically publishing, compiling, evaluating or promoting a JSON/graph edit.
- Introducing a second workflow schema, public API, dependency or authorization policy.
- Editing multiple scenarios in one shared canvas.

## Acceptance criteria

- The Studio header identifies one scenario and project and the organization cannot be switched
  away from that context.
- A new scenario accepts a full `agenthub/v1` Workflow JSON object and displays the resulting graph;
  an empty graph can also be created and edited visually.
- An existing scenario displays its scenario-linked draft, or its active pinned workflow as a
  read-only source that can be explicitly copied into a new scenario-linked draft.
- Switching JSON/graph views preserves a canonical equivalent body. Invalid JSON or compiler-invalid
  JSON does not replace the current graph and produces stable safe diagnostics.
- Saving uses the revision read by the editor; stale writes preserve the local JSON/graph candidate.
- Auditor and cross-tenant users cannot create or edit; server-side scenario/project/organization
  validation is authoritative for create, copy, update, diagnostics and publish.
- No edit changes the active runtime until the existing release lifecycle is explicitly completed.

## Implementation steps

1. Extend the server-owned Builder bootstrap with safe scenario/project labels and the exact active
   workflow projection required for read-only preview/copy.
2. Add an explicitly authorized API operation to create a scenario draft from pasted JSON or the
   trusted active workflow body, reusing existing size, inline-secret and compiler validation.
3. Refactor frontend editor state so validated JSON can atomically replace graph state and graph
   changes continuously produce the JSON view.
4. Make the landing experience scenario-specific and pass locked scenario/project context into all
   creation paths, including AI acceptance.
5. Add backend and frontend tests for new/existing scenarios, round trips, invalid/bounded input,
   immutable source preservation, authorization, tenant isolation and stale revisions.
6. Run focused and full repository checks and update durable behavior/manual evidence.

## Verification plan

- Frontend unit tests for JSON→graph→JSON, graph edits reflected in JSON, invalid candidate
  preservation, scenario labels/locked scope and existing-workflow draft creation.
- Django tests for safe bootstrap projection, active workflow selection, forged scenario/project/
  draft denial, auditor denial, body bounds, validation and non-mutation of artifact/release.
- Full frontend checks, SQLite and PostgreSQL suites, Ruff, mypy, Django check, migration drift,
  compileall and diff checks; no pytest quiet flag or pytest timeout.

## Status

Implemented and automated-verified. Authenticated Turkish owner browser acceptance remains pending.
