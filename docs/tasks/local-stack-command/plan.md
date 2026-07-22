# Task Plan: local-stack-command

## Task summary

Provide one repository-owned PowerShell entry point and one concise runbook for repeatable local
startup on Windows.

## Background

The canonical Compose topology exists, but operators currently repeat frontend build, image build,
migration, startup, status, health, and log commands manually. Host-mode and Compose-mode processes
can also collide.

## Scope

- Add `scripts/local-stack.ps1` with `Update`, `Fresh`, `Status`, `Stop`, and `Logs` actions.
- Make `Update` preserve named volumes while rebuilding and recreating application services.
- Make `Fresh` explicitly confirm before deleting local Compose volumes.
- Build the frontend, validate Compose configuration, wait for health, and show bounded diagnostics.
- Document prerequisites, commands, data behavior, troubleshooting, and host-mode boundaries.
- Route README and the manual testing guide to the command.
- Keep Python dependency installation in a Docker layer keyed only by dependency metadata, with a
  persistent BuildKit pip download cache for legitimate dependency/base rebuilds.
- Skip `npm ci` when the package lock and local Node/npm toolchain fingerprint are unchanged.

## Non-goals

- Production deployment or secret provisioning.
- Automatically seeding demo credentials or changing application behavior.
- Supporting simultaneous host-mode and full-Compose application processes.

## Acceptance criteria

- A clean local stack can be created with one command after prerequisites are installed.
- An existing local stack can be rebuilt on current source without deleting data.
- Destructive volume removal requires `Fresh` plus confirmation or `-Force`.
- Documentation and runtime output identify `Fresh -Force` as a high-risk bypass of the final
  confirmation barrier, suitable only for explicitly disposable automation.
- Failed health checks return a non-zero exit and bounded service state/logs.
- Current-state documentation explains exact behavior and recovery.
- A Python source-only change rebuilds the application package without resolving/downloading Python
  dependencies.
- Repeated `Update` runs skip `npm ci` while `package-lock.json`, Node, and npm are unchanged.

## Affected components

Developer tooling and local operations documentation only.

## Interfaces affected

New local CLI: `scripts/local-stack.ps1`.

## Data impact

`Update` preserves `pgdata` and `miniodata`. `Fresh` deletes local Compose volumes and therefore all
local PostgreSQL and MinIO data after explicit confirmation.

## Security impact

No production credentials or endpoints are introduced. Environment overrides remain injected by the
operator. Commands must not print secret values.

## Authorization impact

None; application authorization is unchanged.

## Observability impact

The command reports Compose state, liveness, and bounded recent logs on failure.

## Migration impact

The existing Compose `migrate` service applies forward migrations on each startup. No migration is
added or rolled back.

## Dependencies

Existing Docker Desktop/Compose and Node/npm prerequisites; no repository dependency change.

## Implementation steps

1. Add the guarded PowerShell lifecycle command.
2. Add the local-stack runbook and link canonical documentation to it.
3. Validate PowerShell parsing, Compose config, help/status behavior, and review the final diff.

## Test plan

- Parse the script without executing it.
- Run `Get-Help` and the read-only `Status` action where permissions permit.
- Run `docker compose ... config --quiet` where Docker client access permits.
- Review destructive-action gating and failure paths manually.

## Rollout plan

Use the new script for future full-Compose local startup; retain documented host mode for specialist
debugging only.

## Rollback plan

Remove the script and documentation links; existing raw Compose commands remain valid.

## Risks

- Docker Desktop or its engine may be unavailable or inaccessible.
- Port 8000 can be occupied by a host-mode process; the script must diagnose rather than kill it.
- `Fresh -Force` intentionally destroys local data; naming and warnings must remain explicit.
- Operators may copy `Fresh -Force` without appreciating its scope; keep it out of routine startup
  examples and place a prominent irreversible-data-loss warning beside its only use.

## Open questions

None.

## Status

Verified.

## Completion criteria

The acceptance criteria have recorded evidence, documentation is current, and final operational and
security review is complete.
