# Verification: Phase 2.8 production static promotion

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Locked frontend + static image build | `docker build -f deploy/Dockerfile --target static-runtime --build-arg STATIC_RELEASE_ID=final-verification ...` | Pass | Node 20.20.0; 7 files/25 frontend tests; 205 modules built; 160 collected then 158 verified assets; final image manifest list `sha256:1b7ffe02...` | Package-supplied source maps were found by the first fail-closed build, explicitly removed, and the verifier still rejects any remaining `.map` |
| Application image build | `docker build -f deploy/Dockerfile --target application --build-arg STATIC_RELEASE_ID=final-verification ...` | Pass | Immutable application target built; image manifest list `sha256:bd4f9294...`; required workflow authoring guide copied as a bounded runtime asset | The application image embeds the matching release in both environment and OCI revision metadata |
| Static runtime HTTP/security | Non-root/read-only `docker run` plus health, JS/CSS, manifest and negative requests | Pass | health 200; JS `application/javascript`; CSS `text/css`; one-year immutable cache and `nosniff`; 158 manifest assets; root/hidden 404; POST 403; user 101; exact release label | `/tmp` was the only writable tmpfs |
| Unsafe release build | Static target with `STATIC_RELEASE_ID=../escape` | Pass (denied) | Build failed on the bounded release-id contract | Prevents path-prefix traversal |
| Production Django settings | Final application image `manage.py check` with matching values, then checks with mismatched URL and image release | Pass | System check clean; URL mismatch and `AGENTHUB_IMAGE_RELEASE_ID must match ...` both denied | `DEBUG=False`; development static routes remain absent |
| Static/manifest contract tests | Isolated Python 3.13 `pytest ... test_static_delivery.py test_manifests.py` | Pass | 9 passed in 4.30s after the immutable-cache review change | Read-only workspace produced one non-functional pytest-cache warning |
| Full repository regression | Isolated Python 3.13 `pytest` with test settings | Pass | 1,028 passed, 60 skipped in 191.04s | Skips are PostgreSQL-only guards; this task changes no database path |
| Formatter/lint | `ruff format --check .`; `ruff check .`; `git diff --check` | Pass | 440 files formatted; all Ruff checks clean; diff whitespace clean | Host Ruff binary remained usable |
| Static typing | Isolated Python 3.13 `PYTHONPATH=/workspace mypy .` | Pass | No issues in 440 source files after the final release-binding change | Host Python launcher was unavailable |
| Django/migration consistency | Isolated image `manage.py check`; `makemigrations --check --dry-run` | Pass | No system issues; no model changes | No database migration |
| GitHub Actions workflow | `rhysd/actionlint:1.7.12` | Pass | No findings | Verification image digest `sha256:b1934e...` |
| Rollback | Serve `rollback-a`, `verification-8bf2405`, then retained `rollback-a` under non-root/read-only constraints | Pass | `rollback_smoke=A-B-A-pass`; each manifest returned its exact release and 158 assets | Proves retained immutable static artifacts can be restored |
| Live OpenShift/browser promotion | Environment-owned registry, rendered overlay, Route/certificate and authenticated builder | Not run | No live cluster/deployment authority or staging identity supplied | Explicit production promotion gate |
| Image CVE/SBOM/signature policy | Organization registry pipeline | Not run | External Docker Scout submission was not authorized; no image metadata was transmitted | Must pass in the approved private/organization pipeline before promotion |

## Acceptance criteria mapping

- Locked build, required-asset failure, checksum inventory and source-map exclusion: image build and
  verifier tests pass.
- Production `DEBUG=False`, version-match and no development static route: production image/settings
  tests pass.
- Non-root/read-only/tokenless/resource-bounded/router-only workload: manifest tests and static
  container smoke pass.
- Shared hostname/path routing and immutable image placeholders: manifest tests pass; environment
  overlays must replace the fail-closed placeholders with exact hosts/digests.
- Correct MIME, safe headers, no listing/hidden files and denied mutation: HTTP and config tests pass.
- Coordinated rollback: A-to-B-to-A container smoke and runbook pass.

## Security requirement mapping

- Artifact includes only collected app static files; source maps, hidden/secret-like files, source
  code and symlinks fail verification.
- Static process runs as UID 101, read-only, with a bounded `/tmp`; OpenShift drops all capabilities,
  uses RuntimeDefault seccomp and disables service-account token mounting.
- Static access logging omits query strings, bodies and cookies.
- Default-deny networking remains; static ingress permits only the OpenShift ingress namespace and
  no egress is added.
- Production web startup rejects mismatched static release values.

## Authorization tests

N/A: deployment-only public static assets confer no application capability.

## Cross-tenant tests

N/A: the artifact and workload contain no tenant-owned data or tenant input.

## Logging and redaction tests

Nginx config inspection proves the log format records method/path/status/size only and omits
`$request_uri`, `$args`, bodies and cookies. Artifact verifier rejects secret-like and hidden names.
No tenant or user content is copied into the image.

## Audit event tests

N/A: application audit is not the authority for deployment changes; environment deployment audit
remains operator-owned.

## Migration verification

N/A: no database migration.

## Behavior comparison with base branch

Before this task, frontend CI built a gitignored bundle without transferring it into an immutable
production artifact; the application image omitted a required workflow-authoring runtime guide;
`collectstatic` was not run; production Uvicorn had no static tier; and OpenShift had one web Route.

After this task, the application and static targets share one locked frontend build, the required
runtime guide is present, `collectstatic` and bounded inventory run fail closed, production settings
require a versioned match, and OpenShift has a dedicated least-privilege `/static` workload/Route.
Local `DEBUG=True` behavior and all application/API contracts remain unchanged.

## Checks not run

- Live OpenShift registry push, digest admission, rendered overlay apply, Route/certificate behavior,
  rollout and rollback.
- Authenticated staging builder browser journey.
- Organization SBOM/signature/vulnerability gate. Docker Scout was not used because it would submit
  private image-derived package metadata to an external service without separate authorization.
- PostgreSQL suite: not applicable to this deployment-only/no-schema change; the full hermetic suite
  records its 60 PostgreSQL-only skips.

## Remaining risks

- A target environment can still misconfigure its hostname, certificate, image digests or admission
  policy; fail-closed placeholders and runbook prevent treating the base draft as deployable.
- Base/container/npm vulnerabilities remain subject to the organization image pipeline.
- Real OpenShift router precedence and authenticated browser rendering are not proven locally.
- Static access is intentionally public; future tenant/user media must never be copied or mounted.

## Human review required

- Platform/SRE: registry, exact image digests, Route hostname/certificate, rendered NetworkPolicy,
  resource sizing, probes, deployment audit and A-to-B-to-A environment rollback.
- Application owner: authenticated staging builder and exact release-prefixed JS/CSS.
- Security/supply chain: private SBOM, signature and critical/high vulnerability policy.

## Final status

**Verified offline/container on 2026-07-29.** Repository production artifacts and fail-closed
deployment contracts are implemented with no unresolved code/configuration critical/high finding.
Live environment and private supply-chain promotion gates remain explicit; the task is not yet
Completed or archived.
