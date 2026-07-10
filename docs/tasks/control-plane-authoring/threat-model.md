# Threat Model: control-plane-authoring

## Assets

- Tenant records (organizations, projects, scenarios, consumers, bindings) and their
  ownership/isolation.
- The authoring paths (console forms, GitOps import) as new write surfaces.

## Trust boundaries

- Operator (browser, LDAP-authenticated) → console write endpoints.
- Reviewed Git YAML → `import_control_plane` → database.

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Non-privileged operator creates records | Writes are role-gated server-side: organization create = platform admin; org-scoped create requires the correct membership role in that org. |
| Operator attaches a child to an org/project outside their scope | Form querysets are limited to the user's scope; the chosen parent is re-validated server-side against `allowed_organization_ids`. Client-submitted ids are never trusted. |
| Operator assigns a project owner from another tenant | Owner choices derive from memberships in the operator's admin scope and form validation requires membership in the selected project organization. |
| Cross-org binding (consumer in A bound to scenario in B) | Model-level clean() already rejects it; the form scopes choices and the importer validates org match. |
| CSRF on console writes | Django CSRF middleware + `{% csrf_token %}` on every form (session-authenticated console). |
| Alias hijack / duplicate | DB `UniqueConstraint(organization, alias)`; surfaced as a form error. |
| Unaudited privileged change | Every create emits an audit event (actor, action, resource, outcome). |
| Malicious GitOps YAML | `yaml.safe_load`; unknown kinds/organizations rejected; capability allowlist enforced on bindings. |

## Residual risk

- Only create is implemented; edit/disable and approval-gated high-risk changes are
  follow-up work. Until then, corrections to a mistaken record use existing controls
  (status via shell/importer) and are audited.
- Role→permission mapping reuses Sprint 1 roles; `platform_admin` is Django
  `is_superuser` for now (see ADR-0001 open question).
