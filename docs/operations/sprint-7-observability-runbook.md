# Sprint 7 Observability Runbook

## Scope and safety

The dashboard and alerts use aggregate telemetry. PostgreSQL remains canonical for
usage and audit. Never paste bearer tokens, prompts, document bodies, consumer data,
or raw eval/tool payloads into incidents, logs, dashboards, or tickets.

## Gateway errors

1. Confirm whether failures affect REST, MCP, or both and identify the bounded operation.
2. Check readiness and recent deployments without exposing dependency details publicly.
3. Correlate safe request/trace IDs with application logs and canonical audit/usage.
4. Disable MCP independently if only MCP fails; do not bypass authorization or audit.
5. Roll back the application only when database compatibility has been verified.

## Latency

1. Separate gateway, runtime/provider, retrieval, database, Redis, and exporter latency.
2. Confirm telemetry export queues are bounded and are not blocking request handling.
3. Check worker queue depth and provider deadlines; do not increase timeouts blindly.
4. Reduce or disable MCP exposure before changing tenant rate limits or safety gates.

## MCP denials

1. Determine whether denials are expected client mistakes or a credential/binding attack.
2. Verify the consumer, binding, capability, and scenario without copying tokens.
3. Revoke a compromised token and preserve audit evidence.
4. Never grant `retrieve_debug` merely to silence a denial alert.

## Telemetry outage

Telemetry export is fail-open and bounded; security/business audit semantics are
independent. Restore the collector/backend, confirm backlog limits, and record the
visibility gap. Do not claim missing telemetry as successful request evidence.
Prometheus uses a secret-backed bearer token in addition to private network controls;
rotate the token through the external secret manager and never paste it into incidents.

## Rollback

Set `MCP_ENABLED=false`, `METRICS_ENABLED=false`, or clear
`OTEL_EXPORTER_OTLP_ENDPOINT` independently. Existing REST, canonical usage, and audit
remain enabled. Network and deployment templates require environment-owner review
before application or rollback.
