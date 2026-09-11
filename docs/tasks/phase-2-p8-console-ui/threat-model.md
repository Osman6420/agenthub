# Threat Model — Phase 2 P8 Console UI

## Assets and trust boundaries

- Tenant documents, immutable versions, document-set membership and retrieval scope.
- Scenario bindings, per-consumer retrieval grants, object bytes and audit evidence.
- Browser input is untrusted. Every target is tenant-scoped and every write is authorized again
  server-side after LDAP/session authentication.

## Threats and mitigations

| Threat | Mitigation and evidence |
| --- | --- |
| Cross-tenant read or mutation through a changed URL/form id | Scoped querysets; foreign scenario, consumer, binding, grant, document and set targets are rejected or return 404. |
| Read-only operator mutates state or ACL | `can_author_scenarios` is enforced server-side; purge uses stronger `can_admin_org`. |
| UI grant appears effective but retrieval ignores it | P4 correction carries authenticated consumer DB id from signed context/durable run and intersects pinned versions with explicit `consumer/retrieve` grants. Missing, disabled, foreign or ungranted consumer gets no document-set chunks. |
| Spoofed free-form ACL principal | P8 accepts only an active same-tenant `Consumer`; the stored opaque reference is its stable database id. |
| ACL removal without evidence | Binding/grant create and remove use fail-closed audited services. |
| Accidental or unauthorized physical purge | Tenant-scoped target, org/platform-admin authorization, prior tombstone and exact logical-id confirmation. The service refuses pinned versions and audits deletion. |
| CSRF or stored markup execution | Mutations are POST-only with Django CSRF; templates retain autoescaping and never render document bytes. |

## Operational and residual risks

- Object deletion precedes transactional metadata/audit deletion. Storage deletion is idempotent,
  but an audit/DB failure can leave metadata pointing to removed bytes until retry.
- Binding changes require release recompilation; the UI states this explicitly.
- `user`, `group` and `service` principals stay inert; P8 exposes consumer grants only.
- Django-managed tenant tables retain the planned non-owner role and broader RLS hardening work.
