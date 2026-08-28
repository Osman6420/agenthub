# Verification: OpenShift deploy portability hardening

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Full SQLite suite | `python -m pytest -q` | Pass | 1309 passed, 61 skipped in 199.88s | Skips are PostgreSQL/RLS/pgvector-specific; one pre-existing cache-write warning |
| Focused profile/deployment suite | focused orchestration, embedding, manifest and static tests | Pass | 63 passed | Includes idempotency, disabled/mismatch denial and platform-admin denial |
| Ruff | `python -m ruff check apps`; `python -m ruff format --check apps` | Pass | 474 files clean/formatted | No control weakened |
| Mypy | `python -m mypy apps` | Pass | 474 source files, no issues | Includes new management command |
| Migration drift | `python manage.py makemigrations --check --dry-run` | Pass | No changes detected | No database migration |
| Helm 3 | Helm 3.21.1 checksum verification; strict lint/render for both charts | Pass | Managed 24 docs; bundled 37 docs | Managed pre-hooks and bundled revisioned Jobs rendered |
| Helm 4 | Helm 4.2.3 checksum verification; strict lint/render for both charts | Pass | Both charts linted/rendered | No Helm 3-only behavior |
| Chart package/version | dependency update plus packaged-child inspection | Pass | `agenthub` and stack 0.2.0; lock digest refreshed; `agenthub-0.2.0.tgz` contains new contract | Old 0.1.0 package is replaced, not overwritten |
| Negative schema | strict lint with invalid mode and non-digest probe image | Pass (denied) | Enum and `sha256` pattern rejected both inputs | Fail-closed values contract |
| Render security audit | parsed Helm 4 renders and audited every Job/Deployment/StatefulSet container | Pass | 35/35 containers/init containers immutable, tokenless, restricted and resource-bounded | 20 workload resources |
| Probe contract | rendered web Deployment inspection | Pass | HTTP `/ready`, service-name Host plus forwarded-HTTPS headers, no TCP readiness | `/live` retained for startup/liveness; no redirect to plaintext port |
| Shell syntax | Git POSIX shell `-n` on both Secret helpers and rendered migration wait script | Pass | No syntax errors | WSL bash was unavailable; Git shell used |
| Binary build contract | PyYAML/template invariant test | Pass | 3 ImageStreams, 3 triggerless Binary BuildConfigs, shared parameters | `oc process --local` unavailable because `oc` is not installed |
| Diff hygiene | `git diff --check` | Pass | No whitespace errors | Existing owner `.gitignore` ZIP entry preserved |

## Acceptance criteria mapping

- Canonical base images are overrideable without a private-registry default.
- Triggerless Binary BuildConfigs and standalone static build are present and tested.
- Managed mode renders pre-hooks; bundled mode renders revisioned normal Jobs compatible with Helm
  wait semantics.
- Profile bootstrap/gates are exact, active-only and fail closed.
- HTTP readiness and virtual-host Host header are rendered.
- Probe image is required and digest-pinned by schema/examples.

## Security requirement mapping

- Restricted-SCC, no-token, immutable-image and full-resource invariants passed on every rendered
  workload and init container.
- Probe commands receive non-secret database components and do not print host/user/password values.
- Values schemas reject mutable probe image references and unknown initialization modes.

## Authorization tests

Pass: a non-superuser platform actor is denied with `PLATFORM_ADMIN_REQUIRED`; neither profile is
created. Existing platform-admin service and audit paths are reused.

## Cross-tenant tests

Not applicable to deployment-only platform catalog state; no tenant query or authorization scope
changed. The full suite retained existing tenant tests.

## Logging and redaction tests

Pass by inspection/render tests: readiness output contains generic state or mismatched field names,
not endpoint values, database URLs, passwords or provider keys. `pg_isready` logs no host/user value.

## Audit event tests

Existing registration service audit tests remained in the passing suite. Read-only checks add no
state-change audit event.

## Migration verification

Pass: `makemigrations --check --dry-run` reported no changes. Migration execution itself remains an
environment rollout action.

## Behavior comparison with base branch

Base behavior used hard-coded Docker bases, only pre-hooks and shell-output existence guards. The
new behavior preserves managed pre-hooks while adding portable build inputs, bundled normal Jobs,
exact idempotent profile validation and semantic readiness. No public application API changed.

## Checks not run

- No image was built/pushed and no BuildConfig was started; Docker daemon access was unavailable.
- `oc process --local` and target server-side dry-run were unavailable because `oc` is not installed.
- No authorized target OpenShift upgrade, Route/SCC/CNI/quota check or live probe was run.
- PostgreSQL-specific full-suite tests remain the 61 recorded skips; the new catalog command uses
  ORM/migration APIs covered on SQLite and requires target PostgreSQL acceptance during rollout.

## Remaining risks

- Organization mirror trust and exact base-image digests remain environment approvals.
- Standalone/canonical static Dockerfiles require the added parity test to remain enforced.
- Helm cannot reverse successful migrations or immutable profile creation.
- Live cluster NetworkPolicy, admission and database-role permissions remain target gates.

## Human review required

Target operators must approve mirror image identities/digests, run Binary builds, review SBOMs,
perform server dry-run, back up data and capture live `--atomic --wait --wait-for-jobs` rollout
evidence before environment promotion.

## Final status

Verified offline on 2026-08-28. Implementation and repository checks are complete; live OpenShift
acceptance is intentionally outstanding and must not be inferred from this record.
