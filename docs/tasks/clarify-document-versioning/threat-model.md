# Threat Model: clarify-document-versioning

## Assets

Architecture source of truth and GitOps artifact compatibility.

## Actors

Developers, coding agents, operators, and GitOps automation.

## Entry points

Architecture documents and artifact YAML import/export.

## Trust boundaries

Git-authored YAML entering the artifact registry remains the only affected boundary.

## Data classifications

Configuration metadata; artifact bodies retain their existing classifications.

## Authentication

Unchanged.

## Authorization

Unchanged; organization scoping remains enforced by existing services.

## Tenant isolation

Unchanged.

## External systems

Potential external GitOps consumers of exported YAML.

## Abuse cases

No new execution path. A misleading schema label could cause consumers to select an incorrect parser.

## Failure cases

An external consumer may reject the corrected `agenthub/v1` label if it encoded the accidental `agenthub/v3` value.

## Logging and audit risks

None introduced.

## Mitigations

Keep import backward-compatible, update all repository examples/tests, and flag external-consumer confirmation for human review.

## Residual risks

Unknown out-of-repository consumers may depend on the old label.

## Required security tests

Existing inline-secret rejection and organization-scoping behavior must remain unchanged.
