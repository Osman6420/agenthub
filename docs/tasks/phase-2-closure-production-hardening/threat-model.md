# Threat Model: Phase 2 closure production hardening

## Assets and trust boundaries

Tenant rows and database roles; uploaded files and quarantine state; document/model inputs and
outputs; connector/model/OCR credentials; CA/DNS/firewall policy; provider budget and audit history.
Boundaries are application/worker → PostgreSQL, upload → scanner → object/index plane, and platform
profile → approved external/private service.

## Principal threats

- Cross-tenant access through missing/leaked tenant context, table ownership or `BYPASSRLS`.
- Malware, polyglot or spoofed content becoming parseable/indexable before a successful scan.
- SSRF, DNS rebinding, credential disclosure or unintended destinations in live profiles.
- Confidential content retention by providers and unbounded cost or response size.
- Blind retry after a dispatched request with an unknown outcome.
- Audit/log leakage of file content, prompts, responses, endpoints or credentials.

## Required controls and tests

FORCE RLS plus a non-owner role; transaction-local context and pool-leak tests; fail-closed scanner
and quarantine; content-based type validation; immutable platform profiles referenced by ID only;
resolved-IP/TLS/redirect/timeout/size controls; synthetic smoke data; redacted audit; cost/rate/token
limits; terminal `outcome_unknown`; documented disable and rollback drills.

For P11.1, table discovery comes only from Django's installed model metadata; catalog lookups and
role/schema/policy values remain bound parameters. Readiness inspection
is read-only. A dynamic inventory prevents a newly-added direct-tenant model from silently falling
outside the report, while explicit bootstrap/telemetry classifications make exclusions visible.
The check is not proof that request and worker context propagation is correct, and passing it must
not be treated as authorization to activate a production role or policy.
The diagnostic requires read access only; write/delete grants must be separately minimized per
table so immutable or append-only records do not gain blanket mutation privileges.

## Residual risk

Concrete provider retention, corporate network topology, scanner effectiveness and operational
ownership cannot be accepted until the selected environment/product inputs are reviewed.
