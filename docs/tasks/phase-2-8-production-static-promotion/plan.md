# Task Plan: Phase 2.8 production static promotion

## Task summary

Close the Phase 2.8 production-promotion gate by producing the workflow-builder bundle and Django
static tree as immutable build outputs, serving them from a dedicated non-root OpenShift workload,
and proving fail-closed promotion and coordinated rollback behavior.

## Background

Local Uvicorn serves Django app static assets only while `DEBUG=True`. Production correctly keeps
`DEBUG=False`, so the current OpenShift web workload cannot serve the generated workflow-builder
JavaScript and CSS. The frontend bundle is intentionally gitignored and the existing frontend CI job
does not transfer its output into a production artifact.

The owner approved a new production static-container dependency and the `/static` OpenShift routing
change on 2026-07-29. No live cluster or production deployment is authorized by this task.

## Scope

- Build the frontend from the pinned npm lockfile inside an immutable container build.
- Run Django `collectstatic` during the build and fail when required builder assets are absent.
- Produce a dedicated non-root, read-only Nginx static-image target.
- Preserve the bounded workflow-authoring guide required by the production runtime image.
- Add an OpenShift static Deployment, Service, Route and least-privilege ingress policy.
- Keep application and static images tied to one release identifier and digest-pinned by overlays.
- Add CI and manifest/static-contract tests, local image smoke evidence and rollback instructions.
- Update current deployment documentation and Phase 2.8 verification/planning records.

## Non-goals

- Applying manifests to a live OpenShift project.
- Provisioning a Route hostname, image registry, certificate, CDN or DNS.
- Serving user uploads, document content or runtime media from the static workload.
- Changing authentication, authorization, tenant isolation, public APIs, database schema or audit.
- Enabling Django development static routes in production.

## Acceptance criteria

- The locked frontend build and `collectstatic` run before a static image can be produced.
- Missing `builder.js` or `builder.css` fails the build and CI.
- Production settings keep `DEBUG=False`; Django does not register development static routes.
- The static container runs non-root on port 8080 with a read-only root filesystem and no
  service-account token.
- Only the OpenShift ingress namespace may reach the static workload.
- `/static` is routed to the static Service on the same environment-supplied host as the web Route.
- JavaScript and CSS return correct content types, security headers and bounded cache policy.
- Application and static image placeholders require environment overlays to pin immutable digests.
- Rollback restores the matching application/static image pair without deleting prior artifacts.
- Repository formatter, lint, type, Django, manifest, frontend and container smoke checks pass.

## Affected components

- `.github/workflows/ci.yml`
- `deploy/Dockerfile`
- `deploy/static/`
- `deploy/openshift/platform.yaml`
- `deploy/openshift/network-policies.yaml`
- `apps/observability/tests/test_manifests.py`
- production/static configuration tests and deployment documentation

## Interfaces affected

- Deployment-only `/static/*` HTTP route.
- Build targets for the application and static images.
- Environment overlay contract for a shared explicit Route hostname and immutable image digests.

No application API contract changes.

## Data impact

No database or tenant data changes. The generated static artifact contains application-owned
JavaScript, CSS and Django app static files only.

## Security impact

A new externally readable static workload is introduced. It must expose only the collected static
tree, reject hidden/unexpected files, run non-root/read-only, emit no directory listing, use safe
content types and headers, and receive ingress only from the OpenShift router.

## Authorization impact

None. Static assets are public executable product resources and confer no application capability.
All product and API authorization remains server-side.

## Observability impact

Container access/error logs go to stdout/stderr without cookies, query values or application data.
Readiness/liveness use a generated non-sensitive health file.

## Migration impact

No database migration. Deployment migration adds a static workload and a path Route. Environment
overlays must deploy the static artifact before switching the web/static Route pair.

## Dependencies

- Existing pinned frontend `package-lock.json`.
- Existing Django staticfiles framework.
- Owner-approved `nginxinc/nginx-unprivileged` production container base, pinned to a fixed release
  in source and resolved/pinned by digest in the organization build environment.
- Environment-supplied OpenShift Route hostname and registry/image digests.

## Implementation steps

1. Add container build stages for locked frontend compilation and `collectstatic`.
2. Add fail-closed asset verification and a non-root Nginx static image target.
3. Add Nginx configuration with `/healthz`, content-type, security and cache controls.
4. Add OpenShift ServiceAccount, Deployment, Service, `/static` Route and ingress policy.
5. Extend manifest/static settings tests and CI build/smoke gates.
6. Document digest pinning, rollout, browser acceptance and coordinated rollback.
7. Run repository checks, inspect the final diff as staff/AppSec/SRE and record evidence.

## Test plan

- Frontend `npm ci`, typecheck, vitest and production build.
- Static asset contract unit tests for required outputs, production settings and URL behavior.
- OpenShift manifest tests for exact routes, host contract, service target, non-root/read-only
  workload, resource bounds, probes, token disablement and least-privilege ingress.
- Docker application/static target builds and container HTTP smoke when Docker is available.
- Browser staging-equivalent smoke for builder JS/CSS status, MIME type and rendered UI when the
  environment permits authentication.
- Repository formatter, lint, mypy, Django checks, migration drift and applicable tests.

## Rollout plan

1. Build application and static targets from the same commit and record both digests.
2. Render an environment overlay with one explicit hostname and both immutable digests.
3. Deploy the static workload first and verify `/healthz` internally.
4. Apply the `/static` Route, verify assets and content types, then roll the web workload.
5. Run authenticated builder and production-settings smoke before promotion.

## Rollback plan

Retain the previous application and static image digests. Roll both Deployment image references back
as one release operation. Do not delete the previous static artifact until the rollback retention
window closes. If only the static deployment fails, keep the prior web/static pair active.

## Risks

- Application/static version skew.
- A shared-host Route mismatch or accidental broad ingress.
- Cache retaining incompatible fixed-name assets.
- Static image including source, secrets or user content.
- Nginx attempting writes under a read-only filesystem.
- Build/promotion succeeding with a missing generated bundle.

## Open questions

- The staging/production Route hostname and registry are environment-owned inputs and remain unset in
  repository drafts.
- Live OpenShift application and authenticated browser acceptance require separate deployment
  authority and credentials.

## Status

Verified offline/container on 2026-07-29. Live registry/cluster/router and authenticated staging
acceptance remain environment promotion gates, so the task is not archived or marked Completed.

## Completion criteria

Acceptance criteria map to passing evidence in `verification.md`; current deployment documentation
matches the delivered contract; final staff/AppSec/SRE review records no unresolved critical/high
finding; live environment checks remain explicitly separated if not authorized.
