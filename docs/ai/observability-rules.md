# Observability Rules

## Application logs

Emit structured logs with timestamp, severity, service, component, environment, build SHA/version, stable event name, request ID, trace ID, safe actor/tenant references, outcome, error code, and duration when applicable. Generate missing request/trace IDs at trusted ingress and propagate them across HTTP/MCP, queues, workers, and dependencies. Use bounded, documented field names and values.

## Sensitive-data policy

Never log passwords, tokens, cookies, authorization headers, API keys, private keys, raw secrets, session material, full request/response payloads, unredacted personal data, document contents, model prompts/responses containing protected data, or database connection strings. Use opaque identifiers, classification-aware redaction, and approved sampling.

## Errors

Return stable, safe client error codes. Do not expose stack traces, SQL, filesystem paths, hostnames, dependency internals, or secret names. Log an exception once at the layer that can add action-oriented context; avoid duplicate logs at every layer.

## Metrics and traces

Measure request/error counts, latency, dependency duration, retry count, queue depth/age, worker saturation, and resource pressure. Trace major boundaries and propagate context. Keep identifiers, exception text, URLs, prompts, and user/tenant values out of metric labels to control cardinality and privacy.

## Security and business audit

Audit authentication success/failure, session create/revoke, authorization denial, role/permission and user lifecycle changes, sensitive access/export, configuration changes, administrative actions, resource create/update/delete/approve/reject, and audit-control changes.

Each event includes event time, actor, effective identity, impersonating identity when present, tenant, action, target type, safe target ID, authorization decision, policy version, outcome, reason code, request ID, trace ID, source channel, and application version as applicable. Specify per operation whether audit persistence failure is fail-closed or an approved fail-open path with durable recovery; security-critical administration defaults to fail-closed.

Audit is separate from debug/application logging. Restrict access, define retention, protect integrity/tamper evidence, and monitor delivery failures. Audit payloads still follow data minimization and redaction.
