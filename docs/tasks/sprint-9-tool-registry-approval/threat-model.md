# Threat Model: sprint-9-tool-registry-approval

## Assets

External systems and data, tool credentials, definitions/bindings, approval authority,
release/checkpoint integrity, tenant data, side-effect correctness, idempotency records,
audit evidence, and network availability.

## Actors

Consumers, workflow/agent runtimes, tool administrators, approvers, platform admins,
external tool operators, compromised models/tools/tenants, and network attackers.

## Entry points

Tool GitOps/import and binding forms, release compiler, workflow tool requests, proxy
MCP/HTTP adapters, secret resolver, approval console/API/MCP, resume tasks, callbacks
if later approved, and tool responses.

## Trust boundaries

Model/workflow request to proxy policy; release binding to destination; proxy to secret
resolver; proxy to external network/tool; requester to approver; approval record to
resume worker; untrusted tool response to workflow/model state.

## Data classifications

Credentials are restricted. Tool inputs/outputs and approval summaries may contain
confidential data/PII. Definitions, risk policy, destinations, and audit metadata are
internal. Side-effect/idempotency state is integrity-critical.

## Authentication

Consumers/operators use existing authentication. Approval identity is server-resolved
and revalidated at decision time. Workloads use distinct least-privilege identities;
external tool authentication comes only from approved secret references.

## Authorization

Proxy verifies capability, organization/scenario, release-pinned binding, allowed
fields, risk, and approval for every attempt. Approval is object/action scoped and
honors separation of duties. Tool/provider success never implies application
authorization.

## Tenant isolation

Definition visibility, binding, approval, request, run, release, secret reference, and
audit target must belong to the same authorized tenant or explicit platform-owned
scope. Shared tools still use tenant-specific bindings and credentials/policy.

## External systems

Registered MCP/HTTP tools, DNS/TLS infrastructure, proxies, secret manager, broker,
Postgres, telemetry backend, and OpenShift network controls. Destinations, redirects,
IP ranges, methods, headers, response sizes, and deadlines are constrained.

## Abuse cases

- Supply arbitrary URL/IP/redirect/DNS result to reach metadata, private, or admin services.
- Invoke another tenant's binding or secret as a confused deputy.
- Forge/replay approval, approve after expiry, self-approve, or swap input after approval.
- Cause duplicate side effects through retry, concurrent decisions, or worker redelivery.
- Exfiltrate secrets/data through headers, URL, payload, errors, redirects, or telemetry.
- Return prompt injection, malformed/oversized output, or false success from a tool.
- Downgrade risk/approval or substitute an unpinned definition after release.

## Failure cases

DNS changes, TLS failure, connect/read timeout, response truncation, secret outage,
provider 5xx/rate limit, local crash after remote success, audit failure, concurrent
approve/reject/cancel, expired approval, and resume on incompatible code/release.

## Logging and audit risks

URLs, headers, approval comments, exceptions, and payloads often contain credentials or
PII. Use destination/tool IDs, hashes, sizes, risk, stable outcomes, and redacted
summaries. Lifecycle mutation audit is fail-closed; external uncertain outcomes are
recorded without retrying blindly.

## Mitigations

Immutable release pins; central default-deny proxy; scheme/host/port/IP allowlists with
post-resolution and redirect checks; NetworkPolicy egress; TLS verification; bounded
timeouts/responses; contract validation; logical secret references resolved from a
corporate manager through the OpenShift External Secrets Operator; scoped workload
identities; encrypted, RBAC-restricted native Secret fallback; approval request checksum
and expiry; separation of requester and approver; transactional single decision;
idempotency keys; explicit uncertain state; output taint/prompt-injection policy;
redaction and audit.

## Residual risks

Exactly-once external side effects cannot be guaranteed without provider cooperation.
Approved tools and approvers can be compromised. DNS/network enforcement varies by
environment. Redacted summaries may be insufficient for an informed approval or may
still reveal sensitive context.

## Required security tests

SSRF including private/link-local/metadata, DNS rebinding and redirects; cross-tenant
tool/secret/approval denial; role and self-approval denial; approval input-swap/replay/
expiry races; duplicate/uncertain side effects; secret and payload redaction; schema/
size/timeout/TLS failures; prompt-injection output handling; risk downgrade/pin
substitution denial; audit failure; and live egress-policy validation where available.
