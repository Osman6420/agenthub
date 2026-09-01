# Operations Standard

Deployment guides:

- [Source ZIP packaging](source-zip-packaging.md) — Git-derived application source handoff with
  installation guides, checksum manifest, and fail-closed local-secret/runtime-data exclusions.
- [OpenShift bundled demo stack with Helm](openshift-bundled-stack-helm.md) — AgentHub plus
  single-replica PostgreSQL/pgvector, Redis and MinIO in one namespace for non-production demos.

- [OpenShift installation with Helm](openshift-helm-installation.md) — preferred packaged install,
  ordered migration/bootstrap hooks, external Secrets and restricted-SCC workloads.
- [OpenShift installation from Ubuntu](openshift-ubuntu-installation.md) — restricted SCC,
  resource limits, immutable images, generic model/embedding profiles and optional external demo;
  lower-level `oc`/Template alternative to Helm.

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
process roles are implemented for local operation. The OpenShift Helm chart, lower-level templates
and Ubuntu installers are reviewable repository artifacts; they are not evidence of a live cluster
deployment. Prometheus-style metrics and opt-in OpenAI-compatible model/embedding adapters are
implemented, while production credentials, destination approval and target-cluster validation
remain environment work.

The Phase 2.8 static-asset production path is implemented and offline/container verified: immutable
application and static image targets, fail-closed frontend/`collectstatic` checks, version-matched
production settings and a non-root OpenShift static workload/Route are present. Live registry,
cluster/router and authenticated-browser promotion remain environment gates. See the
[production static-assets runbook](production-static-assets.md).
