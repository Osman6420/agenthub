# Production static assets: OpenShift rollout and rollback

## Purpose and ownership

This runbook promotes AgentHub application static files through the dedicated OpenShift
`agenthub-static` workload. Platform/SRE owns registry, Route hostname, certificate, namespace,
image-digest admission, deployment audit and rollback execution. Application owners approve the
matching release identifier and authenticated builder smoke.

The repository manifests are safe drafts, not evidence that a live cluster was changed.

## Architecture

One explicit environment hostname has two OpenShift Routes:

- `/static` targets `agenthub-static`, a non-root Nginx workload with no token or egress;
- all other paths target `agenthub-web`, the Uvicorn/Django workload.

The static image contains one immutable `/static/<release-id>/` tree. Production Django requires
`DJANGO_STATIC_URL=/static/<release-id>/` to match `AGENTHUB_STATIC_RELEASE_ID`; startup fails closed
when they differ. The application image also embeds `AGENTHUB_IMAGE_RELEASE_ID` at build time and
startup requires it to match the static release. Fixed builder filenames are therefore isolated by
release prefix.

Release identifiers are permanent content identities and must never be reused. Static responses use
a one-year immutable browser cache; a rollout or rollback changes the release-prefixed URL instead
of replacing content under an existing URL.

## Prerequisites

- Approved OpenShift project, hostname, edge certificate and registry.
- Approved immutable Node, Python and Nginx base images under organization policy.
- CI build, test, SBOM/signature and vulnerability policy for both resulting images.
- Exact application and static image digests from the same reviewed commit.
- A synthetic authenticated staging operator and scenario for browser acceptance.
- Previous application/static digests and release configuration retained for rollback.

Do not place registry credentials, application secrets or certificate material in commands,
manifests, logs or verification records. Use environment-owned secret references and authenticated
CLI sessions.

## Build

Use the same bounded release identifier for both targets:

```bash
RELEASE_ID=<approved-release-id>
APP_IMAGE=<registry>/agenthub:${RELEASE_ID}
STATIC_IMAGE=<registry>/agenthub-static:${RELEASE_ID}

docker build --file deploy/Dockerfile \
  --target application \
  --build-arg STATIC_RELEASE_ID="${RELEASE_ID}" \
  --tag "${APP_IMAGE}" \
  .

docker build --file deploy/Dockerfile \
  --target static-runtime \
  --build-arg STATIC_RELEASE_ID="${RELEASE_ID}" \
  --tag "${STATIC_IMAGE}" \
  .
```

The build runs locked frontend type checking, tests and compilation. The static target then runs
`collectstatic`, removes package-supplied source maps, verifies required builder assets and creates
`asset-manifest.json` with bounded paths, sizes and SHA-256 checksums.

Promotion automation must record and deploy registry digests, never mutable tags.

## Environment overlay

Replace every fail-closed placeholder in `deploy/openshift/platform.yaml`:

- both Route `spec.host` values with the same approved hostname;
- all workload image placeholders with registry digests;
- `AGENTHUB_STATIC_RELEASE_ID` with the exact release identifier;
- `DJANGO_STATIC_URL` with `/static/<release-id>/`;
- the remaining documented dependency, secret-store and environment placeholders.

Render the complete overlay and rerun manifest/policy validation before applying it. Reject the
release if either Route host differs, an image is not digest-pinned, or static URL/release values do
not match.

## Rollout

1. Push both images and complete organization provenance, signature, SBOM and vulnerability gates.
2. Deploy `agenthub-static` first without changing the current web release.
3. Verify both static replicas are ready and `/healthz` returns HTTP 200 `ok`.
4. Apply the `/static` Route with the approved shared hostname.
5. Verify the new release's `asset-manifest.json`, `builder.js` and `builder.css` through the Route.
6. Confirm JavaScript is `application/javascript`, CSS is `text/css`, `nosniff` and same-origin
   resource headers exist, hidden/path-traversal requests return 404, and POST is denied.
7. Deploy the matching web image and release/static configuration.
8. Confirm `manage.py check` under production settings and application liveness/readiness.
9. Sign in with the synthetic staging operator, load the builder, and confirm generated JS/CSS
   return 200 with the exact release prefix and the editor renders without asset/console errors.
10. Record image digests, release identifier, manifest checksum, browser evidence, approver and
    rollback pair before production promotion.

## Fail-closed promotion conditions

Stop before promotion when:

- frontend tests/build, `collectstatic` or static verification fails;
- required assets are absent/empty or a forbidden hidden/source-map/secret-like file remains;
- app/static targets do not come from the same reviewed commit and release identifier;
- an overlay contains a mutable image reference or fail-closed placeholder;
- Route hosts or static release settings differ;
- replicas/probes are unhealthy or content types/security headers are wrong;
- the authenticated staging builder does not render;
- the prior rollback pair is unavailable.

## Rollback

Rollback is one reviewed release operation:

1. Restore the previous static image digest.
2. Restore the previous web image digest.
3. Restore the previous `AGENTHUB_STATIC_RELEASE_ID` and matching `DJANGO_STATIC_URL`.
4. Wait for static and web readiness.
5. Repeat asset, production-settings and authenticated builder smoke.

Do not remove either the failed or previous image during rollback. Retain prior application/static
pairs for the environment's rollback window. Never attempt rollback by enabling `DEBUG`, adding
Django development static routes or mixing image/release identifiers.

## Safe diagnostics

- Inspect rendered Route hosts, paths, Service targets, image digests and release environment values.
- Read bounded static pod logs; the configured log format omits query strings, cookies and bodies.
- Compare the public `asset-manifest.json` release/checksums with CI evidence.
- Inspect pod readiness, restart count, resource pressure and OpenShift router status.

Escalate Route/certificate/registry/admission failures to Platform/SRE. Escalate a checksum,
missing-asset or builder-render mismatch to the application owner and keep the prior pair active.
