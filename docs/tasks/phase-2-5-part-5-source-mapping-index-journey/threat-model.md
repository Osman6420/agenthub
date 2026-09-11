# Threat Model: phase-2-5-part-5-source-mapping-index-journey

## Assets
Connector credentials and endpoints, private operator inputs, synthetic samples, normalized documents, tenant source/run state, document-set versions and indexes.

## Actors
Platform administrators, organization/project owners, scenario editors, release managers, auditors, unauthenticated users and cross-tenant users.

## Entry points
Set-scoped connector workspace, source detail, mapping preview/create, source create, run-now and schedule configuration routes.

## Trust boundaries
Browser→Django, organization→platform profile grant, synthetic JSON→mapping validator, source→connector worker, sync result→document draft, staged index→promotion gate.

## Data classifications
Credentials/endpoints/operator inputs/content are restricted; identifiers, safe counts, stable status and redacted failure codes are internal operational metadata.

## Authentication
All console routes require authenticated Django sessions and CSRF for mutations.

## Authorization
Tenant-scoped reads; scenario-author permission for source authoring/run/stage scheduling; release-manager permission for promotion automation; auditors read only.

## Tenant isolation
Every source, set, run and index projection is constrained through the authorized document set and organization. Cross-tenant identifiers return 404.

## External systems
Confluence, generic REST and embedding endpoints are accessed only by existing governed workers/profiles. Synthetic preview performs no egress.

## Abuse cases
Guessing source IDs, binding a foreign profile/contract, injecting URL/header/secret inputs, oversized samples, exposing raw exceptions/content, or presenting an unpromoted index as active.

## Failure cases
Broker or connector failure, incomplete sync, mapping rejection, missing draft/published version, failed/stale staged index and audit persistence failure in existing mutations.

## Logging and audit risks
Raw exceptions or form values could expose secrets. Continue stable safe codes and existing audit events; do not add raw payload logging.

## Mitigations
Explicit safe view models, existing grants and role checks, bounded schemas/samples, no-egress preview, tenant/set filters, POST+CSRF mutations, immutable contracts/versions and explicit promotion.

## Residual risks
Authenticated owner visual review and real connector operational acceptance require configured credentials and remain manual.

## Required security tests
Authentication denial, auditor mutation denial, cross-tenant 404, profile/input/content redaction, preview no-egress/bounds, safe failure codes and tenant-scoped lifecycle/index projection.
