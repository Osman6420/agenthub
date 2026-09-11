# Threat Model: sprint-1-tenant-identity-catalog

## Assets

- Tenant data (organizations, projects, scenarios) and its isolation boundary.
- Operator identities and directory-group→role mapping.
- Consumer credentials/subjects and their scenario bindings.
- The append-only audit trail.

## Trust boundaries

- Corporate LDAP/AD → console authentication (human operators).
- Browser/operator → console (session-authenticated, role/tenant scoped).
- Application → PostgreSQL (tenant rows share one database; isolation is enforced
  in code, not by separate schemas).

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Cross-tenant read (operator or query sees another org) | Isolation enforced in querysets/services via `allowed_organization_ids(user)`; negative tests assert org A cannot see org B. UI never widens scope. |
| Privilege escalation via client-supplied role/tenant | Roles derive from `is_superuser` + `OrganizationMembership` + directory groups, resolved server-side; request/form values are never trusted for authorization. |
| Alias collision / hijack within a tenant | DB `UniqueConstraint(organization, alias)`; aliases are closed/redirected, not deleted. |
| Disabled consumer still authorized | Binding resolution checks consumer and binding status; disabled → denied (tested). |
| Unknown/over-broad capability granted to a binding | Capabilities validated against a fixed allowlist on save. |
| LDAP credential theft / bind over cleartext | LDAPS only; bind service-account secret from secret manager; failed binds fail closed; no operator passwords stored. |
| LDAP injection via username | Parameterized filters from `django-auth-ldap`; input not concatenated into filters. |
| Broad model-level mis-authorization via Django Admin | Django Admin removed from routed surface; dev-only opt-in defaults off. |
| Audit tampering | Append-only service; no update/delete path; mutation attempts rejected. |
| Sensitive data in logs/audit | Audit stores actor/action/resource/outcome/reason only; no secrets or raw PII; observability rules apply. |

## Residual risk

- LDAP is not exercised in local/CI verification (python-ldap build); the
  disabled-fallback path is tested. First real LDAP bind must be validated in a
  Linux environment against the directory before enabling in production.
- Single-database multi-tenancy relies on code-level isolation; correctness is
  covered by tests but not by physical separation.
