# Threat Model: Phase 2.8 production static promotion

## Assets

- Workflow-builder JavaScript/CSS integrity and availability.
- Application/static release-version consistency.
- OpenShift Route, image digest and deployment configuration.
- Browser trust in same-host executable resources.
- Source, secrets, user content and internal deployment metadata that must not enter the artifact.

## Actors

- Authenticated AgentHub operators loading the builder.
- Unauthenticated clients requesting public static paths.
- CI/build and OpenShift deployment identities.
- Platform/SRE operators performing promotion or rollback.
- An attacker probing paths, cache behavior, content types or mutable image tags.

## Entry points

- Container build context and npm/Python dependency inputs.
- Nginx `/static/*` and `/healthz` HTTP paths.
- OpenShift Routes and Services.
- Environment overlay hostname and image references.

## Trust boundaries

- Source repository to container build.
- Generated frontend output to Django `collectstatic`.
- Static image registry to OpenShift.
- OpenShift router to the static pod.
- Static JavaScript executing in an authenticated operator browser.

## Data classifications

Collected product static assets are public application code. Secrets, source maps unless explicitly
approved, source code, logs, user uploads, document content and environment configuration are
prohibited from the artifact.

## Authentication

Static assets are intentionally unauthenticated. Product pages and APIs retain existing
authentication. The build and registry identities are environment-managed and not represented in
repository manifests.

## Authorization

The static workload performs no product authorization and exposes no mutable operation. Registry
push and OpenShift apply permissions remain outside the workload and must follow least privilege.

## Tenant isolation

The workload contains no tenant-specific data and accepts no tenant identifier. Tenant media and
documents must never be mounted or copied into it.

## External systems

- Owner-approved Nginx unprivileged base-image registry.
- Organization image registry.
- OpenShift router and cluster.

No runtime egress is required.

## Abuse cases

- Request path traversal or encoded traversal to read files outside the static root.
- Directory listing or fallback exposing unexpected files.
- MIME confusion causing executable content to be interpreted incorrectly.
- Cache poisoning/version skew between application HTML and builder assets.
- Mutable tag replacement or wrong digest deployment.
- Build-context inclusion of `.env`, secrets, source maps or user data.
- Route host collision sending `/static` to an attacker-controlled Service.
- Denial of service with oversized request bodies or noisy logs.

## Failure cases

- Frontend build or `collectstatic` fails.
- Required builder assets are missing, empty or duplicated.
- Nginx cannot start with a read-only filesystem.
- Static Route is applied before the workload is ready.
- Static and web releases use different identifiers.
- Rollback changes only one of the image references.

## Logging and audit risks

Static access logs can leak query strings or excessive client metadata. Configuration must avoid
logging request bodies, cookies and query strings. Deployment changes are platform operations and
must be captured by the environment's deployment audit; no application audit event is appropriate.

## Mitigations

- Locked npm install and fixed base-image release; environment digest pinning required.
- Multi-stage build copies only generated/collected static output.
- Explicit required-file verification before image completion.
- Nginx `alias`/root configuration with no autoindex or broad fallback.
- Correct MIME mapping, `nosniff`, frame/referrer/content security headers and request-size bound.
- Non-root, read-only filesystem, dropped capabilities, RuntimeDefault seccomp, token disabled and
  explicit CPU/memory limits.
- Default-deny networking plus router-only ingress; no egress policy.
- Shared explicit Route hostname asserted by manifest tests.
- Coordinated application/static digest rollout and rollback with previous artifacts retained.
- Production-settings test proves Django development static serving remains disabled.

## Residual risks

- Base images and npm packages require normal vulnerability/SBOM/signature review in the organization
  pipeline.
- Repository tests cannot prove a real cluster's router precedence, certificate, registry admission
  or enterprise policy configuration.
- Authenticated visual acceptance requires an authorized staging session.

## Required security tests

- Path traversal and hidden-file requests do not expose content.
- Directory listing is disabled.
- Required security headers and content types are present.
- Static pod runs non-root/read-only with all capabilities dropped and no service-account token.
- NetworkPolicy admits only the OpenShift ingress namespace.
- Routes share one explicit hostname contract and `/static` targets only the static Service.
- Production Django URL configuration does not add `staticfiles_urlpatterns`.
- Artifact inventory contains only allowlisted collected static files and no secret/source patterns.
