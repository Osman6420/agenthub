# Threat Model: local-stack-command

## Assets

Local PostgreSQL/MinIO data, locally injected provider credentials, and developer processes.

## Actors

Repository developers and coding agents operating their own local environment.

## Entry points

PowerShell parameters and environment variables; Docker Compose and npm subprocesses.

## Trust boundaries

The script passes fixed repository-owned arguments to local Docker/npm executables. Existing process
environment is trusted as operator-controlled local configuration but is never echoed.

## Data classifications

Local development data and potentially secret environment variables.

## Authentication

N/A; local workstation tooling.

## Authorization

OS and Docker daemon permissions remain authoritative.

## Tenant isolation

Application behavior is unchanged. `Fresh` removes the entire local development database, not an
individual tenant.

## External systems

Docker registries and npm registry may be contacted by normal build/install operations.

## Abuse cases

- Accidental volume deletion through an ambiguous command.
- Copy/paste use of `Fresh -Force` bypassing the final human confirmation barrier.
- Shell injection through parameters.
- Secret disclosure through verbose environment output.

## Failure cases

Missing prerequisites, inaccessible Docker daemon, failed frontend/image build, migration failure,
port collision, unhealthy service, or interrupted startup.

## Logging and audit risks

Compose application logs may contain application-level data. Only bounded recent logs are shown;
the script does not dump environment variables.

## Mitigations

- Closed action set and no arbitrary command/string evaluation.
- `Fresh` confirmation with explicit `-Force` for non-interactive use.
- Prominent documentation and red runtime warnings classify `Fresh -Force` as destructive and limit
  it to positively identified disposable automation.
- `Update` never calls `down --volumes`.
- Fail-fast external commands, health timeout, bounded diagnostics, and non-zero failures.
- No automatic process termination.

## Residual risks

An operator intentionally using `Fresh -Force` loses local Compose data. Registry availability and
the security of locally configured provider values remain workstation concerns.

## Required security tests

Review action validation, destructive confirmation, absence of secret output, and fixed subprocess
arguments.
