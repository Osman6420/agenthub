# Task Plan: Builder node configuration parity

## Task summary

Make the visual Builder expose every configuration field that the current workflow
compiler/runtime intentionally supports, without inventing new runtime capabilities or exposing
secrets, endpoints, or cross-tenant metadata.

## Scope and acceptance criteria

- Inventory every built-in node against compiler and runtime behavior.
- Add missing `generate` prompt/model role fields and the current `format_output` literal output
  field to the server-owned node schema.
- Preserve no-config behavior for `input`, `retrieve`, `validate_contract`, and `end`.
- Preserve existing condition, tool, and custom-node forms and tenant-scoped enum projections.
- Optional blank fields must be omitted from serialized config rather than sent as invalid empty
  identifiers.
- Backend and frontend tests prove the complete node matrix and safe form behavior.

## Non-goals

- Expanding the workflow DSL or tightening the legacy `format_output` compiler contract.
- Exposing artifact bodies, tool endpoints, credentials, or unrestricted destination choices.
- Changing release binding, runtime execution, authentication, authorization, or dependencies.

## Verification

Run frontend tests/typecheck/build, focused builder/workflow tests, Ruff, mypy, Django check,
migration drift, compileall, and diff checks. No pytest quiet flag or pytest timeout.

## Status

Implemented and automated-verified; authenticated Turkish browser review remains pending.
