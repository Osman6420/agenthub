# Superadmin recovery runbook

The Django superadmin is a separate exceptional recovery identity. It is not a daily operator role
and must not be added to an organization membership or delegated assignment. Phishing-resistant MFA
is a Phase 3 hardening item; the initial-stage exception uses a unique strong password.

## Before use

1. Confirm that ordinary Global or Organization Administrator authority cannot perform the required
   identity/authorization recovery.
2. Open an incident or approved maintenance record with operator, purpose, affected organization,
   expected actions and rollback.
3. Retrieve the password through the approved guarded credential channel. Do not paste it into
   tickets, chat, shell history or logs.
4. Confirm the `AgentHubSuperadminActivity` alert is loaded and Security/Operations can receive it.

## Recovery

1. Sign in only through the operator console over the approved trusted administrative path.
2. Confirm an immediate `superadmin.login` audit event and alert.
3. Perform only the minimum recovery action. Every console route is fail-closed on the pre-action
   `superadmin.console_access` audit write; an audit persistence failure must stop the request.
4. Record safe public identifiers and outcomes in the incident. Never copy document content,
   secrets, tokens or raw retrieval context into the record.
5. Verify the repaired object with a non-superuser administrator whenever possible.

## Close and review

1. Log out and close the administrative session.
2. Rotate the password after suspected exposure, unplanned use or personnel/custody change.
3. Security/Operations reviews `superadmin.login` and `superadmin.console_access` events against the
   approved record, including actor ID, route, organization ID, request ID and outcome.
4. Treat missing audit evidence, an unexpected alert or unexplained use as a security incident.

## Failure and rollback

- If audit storage or alert delivery is unhealthy, do not continue normal recovery. Restore those
  controls first or use the separately approved incident exception.
- Roll back the recovered application state through normal audited services. Never erase audit
  evidence, grant routine superuser access, disable authorization/RLS or reset protected data.
