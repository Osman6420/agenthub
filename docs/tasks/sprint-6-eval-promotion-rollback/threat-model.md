# Threat Model: sprint-6-eval-promotion-rollback

## Assets

Active release pointer, immutable release/artifact/index pins, eval evidence, canary
assignments, consumer isolation, audit history, and production response integrity.

## Actors

Platform admins, organization release managers, eval workers/operators, authenticated
consumers, and malicious/compromised tenant operators.

## Entry points

Custom console lifecycle forms, management commands, EvalSuite GitOps artifacts,
candidate runtime invocation, and gateway release selection.

## Trust boundaries

Reviewed YAML to eval loader; operator identity to lifecycle authorization; candidate
release to isolated runtime; consumer binding to canary routing; lifecycle transaction
to append-only audit.

## Data classifications

Eval inputs may contain confidential tenant test data. Reports contain identifiers,
assertion outcomes, and usage only. Raw inputs/outputs must not enter logs/audit.

## Authentication

Console uses existing LDAP/session authentication. CLI actor usernames are resolved to
real Django users before authorization. Gateway retains bearer-token authentication.

## Authorization

Release-manager membership is checked against the release scenario organization for
every eval/canary/promote/rollback action. Platform admin is the only cross-org role.

## Tenant isolation

Eval suite, release, index pins, canary consumer, and rollback target must share the
same organization/scenario. Gateway canary resolution happens only after successful
consumer binding authorization for that scenario.

## External systems

Existing model/retrieval providers may be called by candidate eval with their existing
timeouts and destination controls. No new external system is introduced.

## Abuse cases

- Promote without eval or using another release's report.
- Forge actor/organization in CLI or form submissions.
- Assign another tenant's consumer/release to canary.
- Publicly invoke arbitrary candidate ids or bypass active binding.
- Eval bomb with unbounded cases/input/assertions.
- Roll back to a never-active, failed, or different-scenario release.
- Leak eval prompts/output through reports, errors, logs, or audit.

## Failure cases

Provider failure mid-eval, partial result persistence, audit failure, concurrent
promotion/rollback, expired canary, stale cache, and missing retained indexes.

## Logging and audit risks

Assertion failures can contain expected/actual content. Persist stable codes and paths,
not raw values. Audit persistence for lifecycle mutations is fail-closed.

## Mitigations

Allowlisted bounded assertions; exact release and tenant pins; DB transactions and row
locks; single-active constraint; latest passing report bound to release/suite checksum;
release-manager checks; same-org/scenario constraints; time-bounded canaries; fresh
active/canary lookup per request; redacted reports and audit.

## Residual risks

Deterministic tests cannot establish semantic quality. Manual release-manager account
compromise remains high impact. Automatic canary anomaly detection depends on Sprint 7
metrics and alerting.

## Required security tests

Missing/failed/stale eval denial, cross-tenant suite/report/canary/rollback denial,
unauthorized role denial, candidate-id injection denial, expired-canary behavior,
concurrent promotion, audit failure rollback, and output/report redaction.
