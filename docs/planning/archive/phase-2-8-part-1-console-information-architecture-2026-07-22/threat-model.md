# Threat Model: phase-2-8-part-1-console-information-architecture

## Assets

- Organization, project, scenario, document-set, artifact, release and run metadata.
- Organization membership, role assignments and effective action permissions.
- Exact release/artifact/index provenance and operational health state.
- Existing business/security audit evidence and tenant-isolation guarantees.

## Actors

- Authenticated organization members with read access.
- Organization administrators, scenario authors, release managers, approvers and auditors.
- Platform administrators with explicit cross-organization visibility.
- Anonymous, membership-less, disabled-organization and malicious authenticated users.

## Entry points

- `/console/`, organization selection and legacy organization workspace URLs.
- Project, scenario, document-set, artifact, release and run list/detail links.
- Legacy GET list routes that gain contextual redirect behavior.
- Query parameters and session state carrying organization or filter context.
- Existing POST/action routes adjacent to redirected GET routes.

## Trust boundaries

- Browser-supplied path/query/session values → authenticated console request handling.
- Allowed-organization resolution → active-organization convenience context.
- Membership-scoped target resolution → related-object expansion and redirect construction.
- Presentation visibility → independent server-side mutation authorization.
- Django application queries → PostgreSQL transaction-local tenant/RLS scope.

## Data classifications

- Object names, slugs, statuses, relationships and safe run/index summaries: tenant-confidential.
- Membership and authorization topology: tenant-confidential/security-sensitive.
- Document/prompt/run content, credentials and token material: restricted and out of Part 1
  presentation scope.

## Authentication

Existing Django session authentication remains unchanged. Anonymous requests retain the current
login behavior. Part 1 adds no authentication mechanism or account lifecycle operation.

## Authorization

Existing role predicates remain authoritative. Hiding or showing a navigation item never grants or
denies an operation. Every detail and action lookup resolves through the user's allowed scope before
related metadata is rendered. Disabled organizations keep their current read-only rules.

## Tenant isolation

The selected organization narrows presentation only. It cannot expand `allowed_organization_ids`
or PostgreSQL RLS scope. Path IDs, public IDs, slugs, query filters, form values and stale session
state are untrusted. Cross-tenant and nonexistent targets must be indistinguishable to unauthorized
callers and must not appear in redirect `Location` headers.

## External systems

None added. Part 1 performs no external egress and introduces no new dependency.

## Abuse cases

- Forge an organization/project/scenario ID to obtain a redirect containing a foreign slug or name.
- Supply a foreign or malformed filter and infer object existence from different redirect targets,
  status codes, counts or timing.
- Abuse a `next`/target parameter as an open redirect.
- Send POST to a legacy list/action path and have a generic redirect replay or downgrade the method.
- Select an authorized organization, then access relationships lazily evaluated outside the narrowed
  tenant context.
- Use hidden UI actions directly despite insufficient role permissions.
- Infer privileged global health or run counts from the organization home.

## Failure cases

- Redirect loop between an old list route and the new contextual landing page.
- Missing active organization sends a multi-membership user to an arbitrary tenant.
- Stale session organization survives membership removal.
- Health row points to a deleted/inaccessible object and discloses its former identifier.
- Tab refactor omits a critical action/status or changes POST target/method semantics.
- Sidebar fixes make navigation unreachable at narrow widths or by keyboard.

## Logging and audit risks

Redirect diagnostics could log raw query strings, foreign IDs, object names or session context.
Navigation/page views must not create business-audit noise. Existing mutations must keep their
actor, action, target, authorization decision, outcome, reason and trace records; template/route
refactoring must not bypass the audited service path.

## Mitigations

- Construct redirects only with internal named routes and server-resolved authorized objects; do not
  accept arbitrary redirect URLs.
- Clear stale/forged active-organization state and apply the existing deterministic safe default.
- Allowlist preserved query parameters and values; drop unknown or foreign filter inputs.
- Limit redirect behavior to explicitly inventoried GET/HEAD list/workspace routes. Preserve every
  POST/action handler and test unsafe methods directly.
- Resolve target objects inside membership scope, then narrow related queries to the trusted
  organization; retain PostgreSQL non-owner RLS verification.
- Keep server-side role/action checks unchanged and test direct unauthorized requests.
- Render only safe organization-scoped health aggregates and exact authorized links.
- Use stable low-cardinality route/reason diagnostics without raw query strings or tenant content.
- Test redirect loops, open redirect attempts, foreign `Location` leakage and stale relationships.

## Residual risks

- Redirect timing may still differ between malformed and inaccessible requests; status/body/location
  must remain enumeration-resistant and timing is monitored rather than claimed constant-time.
- Contextual navigation can reduce discoverability for legitimate multi-project users; this is a UX
  risk, not a reason to reintroduce an unscoped catalogue.
- Platform-admin visibility remains broader by design and must stay visually explicit.

## Required security tests

- Member, multi-member, membership-less, auditor, admin, platform-admin and disabled-organization
  route matrices.
- Foreign/malformed organization, project, scenario, document-set, artifact, release and run inputs
  return safe outcomes without metadata in body or `Location`.
- Stale active-organization session after membership removal fails closed and is cleared.
- Open-redirect payloads and unallowlisted filters are rejected or discarded.
- POST/PUT/PATCH/DELETE requests to touched routes are never converted into contextual GET redirects.
- Direct hidden-action requests still enforce the existing role predicate and generate no success
  audit on denial.
- PostgreSQL non-owner tests prove singleton tenant scope and transaction-local reset.
- Logs/audit do not contain raw query strings, foreign identifiers, content, secrets or tokens.
