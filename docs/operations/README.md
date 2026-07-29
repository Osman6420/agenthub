# Operations Standard

Repository-owned operational controls and deployment manifests are verified as drafts unless their
task evidence explicitly records a live environment. The following sections define required
documentation before a component is production-ready; a reviewed draft is not evidence of an
applied production change.

## Deployment

Document environments, artifact provenance, topology, release gates, health checks, progressive delivery, and ownership.

## Configuration and secrets

List validated configuration names, safe defaults, reload behavior, and approved secret injection/rotation. Never include secret values.

## Monitoring and alerting

Define service objectives, dashboards, actionable alerts, routing, severity, runbook links, and low-cardinality telemetry.

## Backup and restore

State scope, encryption, retention, RPO/RTO, restore procedure, and evidence from scheduled restore tests.

## Incident response

Define triage, containment, escalation, communication, audit preservation, evidence handling, and post-incident review.

## Rollback

Document application/configuration/data rollback or forward-fix triggers, compatibility windows, approvals, and verification.

## Runbooks

Each runbook names symptoms, prerequisites, safe diagnostic steps, bounded remediation, verification, escalation, and owner. Production access must be least-privileged, approved, and audited.

PostgreSQL/pgvector, Redis, object-storage configuration, and distinct Django/Celery
process roles are implemented for local operation. OpenShift manifests,
Prometheus-style metrics, production credentials, and production embedding/model
adapters remain future work.

The Phase 2.8 static-asset production path is implemented and offline/container verified: immutable
application and static image targets, fail-closed frontend/`collectstatic` checks, version-matched
production settings and a non-root OpenShift static workload/Route are present. Live registry,
cluster/router and authenticated-browser promotion remain environment gates. See the
[production static-assets runbook](production-static-assets.md).
