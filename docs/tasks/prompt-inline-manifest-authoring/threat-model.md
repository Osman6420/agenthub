# Threat Model: prompt-inline-manifest-authoring

## Assets

Prompt artifact bodies, immutable artifact history, exact manifest pins, organization boundaries.

## Actors

Authorized artifact viewers/authors and unauthorized or cross-tenant users.

## Entry points

Exact artifact preview and artifact draft/update/publish console APIs.

## Trust boundaries

Browser state is untrusted. Django service authorization and artifact validators remain authoritative.

## Data classifications

Prompt text is tenant-authored application content and may contain sensitive business instructions;
it must not be logged or rendered as active HTML.

## Authentication

Existing authenticated console session and CSRF protections apply.

## Authorization

Preview and every mutation are independently checked server-side. UI capability flags do not grant
permission.

## Tenant isolation

All referenced IDs are resolved within the scenario organization by existing APIs; foreign IDs must
continue to fail closed.

## External systems

None.

## Abuse cases

Stored script content, oversized bodies, forged capability flags, cross-tenant artifact IDs, stale
draft revisions, repeated publish clicks.

## Failure cases

Preview races, update conflicts, publish validation failure, network loss after publication but before
local manifest selection.

## Logging and audit risks

Status and audit records must not contain prompt bodies. Existing artifact mutation audit is reused.

## Mitigations

Bounded preview projection, textarea rendering, server authorization and validation, disabled busy
actions, optimistic revision checks, exact published IDs, and preserved client text on failure.

## Residual risks

A failed flow can leave a reusable artifact draft. A network failure after successful publication may
require selecting the newly published exact version on retry.

## Required security tests

Existing backend preview and artifact-draft authorization/cross-tenant tests remain authoritative;
this UI unit adds read-only capability coverage and performs no authorization inference.
