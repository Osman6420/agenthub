# Security Rules

## Authentication and authorization

Authentication establishes identity; authorization decides whether that identity may perform an action. Deny by default and enforce every decision server-side at object, action, tenant, and field level. Never trust client-supplied role, owner, tenant, scope, or permission values.

Carry both authenticated and effective identity for impersonation. Authorize impersonation explicitly and audit its start, use, and end. Bind every query and mutation to the verified tenant and prevent cross-user/cross-tenant access. Apply least privilege to users, services, workers, tools, databases, and credentials. Add negative authorization and isolation tests for every protected operation.

## Input and output security

Use explicit schemas and allowlists. Validate type, length, range, format, encoding, and nesting; reject or intentionally ignore unexpected fields. Use parameterized queries and context-aware output encoding. Prevent injection, shell/command execution, path traversal, SSRF, unsafe deserialization, mass assignment, and unsafe uploads.

For files, validate content and size independently of filename and store outside executable paths. For outbound requests, restrict schemes/domains/IP ranges, block metadata/private networks unless required, set connection/read deadlines, cap redirects and response sizes, and validate returned content.

## Secrets and sensitive data

Secrets are forbidden in source, tests, fixtures, logs, examples, and documentation. Inject them through an approved secret manager/environment mechanism with rotation and least privilege. Use synthetic or anonymized test data. Minimize collection and retention. Redact tokens, cookies, authorization headers, passwords, private keys, credentials, and sensitive payloads before telemetry or errors.

## Dependencies and supply chain

Prefer existing approved dependencies. Production dependency changes require explicit approval, provenance/licence/maintenance review, and lockfile consistency. Do not run unknown packages or downloaded scripts. Run applicable dependency, image, static-analysis, and secret scans once repository tooling exists; record results and exceptions.

## Security review checklist

- [ ] Assets, actors, entry points, trust boundaries, and data classifications are recorded.
- [ ] Authentication and object/action/tenant/field authorization are server-side and default-deny.
- [ ] Cross-user, cross-tenant, impersonation, and privilege-escalation cases are denied and tested.
- [ ] Schemas, query parameterization, encoding, upload/path/command/deserialization defenses are adequate.
- [ ] Outbound access has destination, timeout, redirect, and size controls.
- [ ] Secrets and personal/sensitive data are minimized, protected, and redacted.
- [ ] Dependencies and artifacts have reviewed provenance and consistent locks.
- [ ] Security/audit events exist without sensitive data.
- [ ] Failure, retry, rollback, and abuse behavior fail safely.
- [ ] Residual risks, unavailable scans, and required human review are recorded.
