# Task Plan: source-distribution-zip

## Task summary

Create a reviewed, repeatable source ZIP workflow and produce a current OpenShift installation package.

## Background

The repository has canonical OpenShift installation guides but no canonical source-archive guide or packaging command. Ad-hoc desktop ZIP creation can omit required files or include local secrets and runtime data.

## Scope

- Add a PowerShell source-package script.
- Add an operations guide describing package contents, exclusions, creation, and verification.
- Package the current tracked source plus explicitly requested, non-ignored working-tree additions.
- Include an archive-local README and SHA-256 file manifest.

## Non-goals

- Building or distributing container images.
- Exporting secrets, environment-specific values, databases, object-store data, or Git history.
- Changing application or deployment behavior.

## Acceptance criteria

- The ZIP contains the application source, Helm chart, OpenShift installation guide, and current RLS fix files.
- Ignored/local secret and runtime paths are absent.
- Every packaged repository file has a SHA-256 entry.
- The archive can be extracted and its required files are readable.
- The ZIP itself has a reported SHA-256 digest.

## Affected components

Developer/operations tooling and documentation only.

## Interfaces affected

New `scripts/package-source.ps1` command-line interface.

## Data impact

Read-only access to repository files; writes a generated ZIP under `dist/` and temporary staging files that are removed after creation.

## Security impact

Reduces accidental secret leakage by deriving candidates from Git and applying a fail-closed sensitive-path denylist. See `threat-model.md`.

## Authorization impact

None. No application authorization or tenant-isolation behavior changes.

## Observability impact

The script prints archive path, entry count, source state, and SHA-256 digest. No application logging changes.

## Migration impact

None.

## Dependencies

Git, PowerShell, and the .NET ZIP library already available with PowerShell.

## Implementation steps

1. Define Git-derived inclusion and explicit security exclusions.
2. Add the packaging script and operational guide.
3. Create a ZIP from the current working tree with non-ignored untracked files explicitly enabled.
4. Inspect, extract, scan, and hash the archive.
5. Record evidence and complete staff/security/SRE diff review.

## Test plan

- PowerShell parser validation.
- Create package and list all ZIP entries.
- Assert required source and guide entries exist.
- Assert forbidden path and sensitive-extension patterns are absent.
- Extract to a fresh temporary directory and verify the internal checksum manifest.
- Run `git diff --check` for repository edits.

## Rollout plan

Distribute the generated ZIP and its SHA-256 digest through an approved channel. Operators follow the packaged Helm installation guide and supply environment secrets separately.

## Rollback plan

Delete the generated ZIP and revert the packaging documentation/script if the workflow is rejected. No runtime rollback is required.

## Risks

- Git-tracked sensitive material would otherwise be eligible; an explicit denylist and archive scan mitigate this but do not replace human review.
- `-IncludeUntracked` can include unintended non-ignored files; the script records this mode and the resulting entry list is reviewed.
- A dirty snapshot is not a reproducible release; package metadata identifies the commit and dirty state.

## Open questions

None. This package is a working-tree source handoff, not a signed production release.

## Status

Completed.

## Completion criteria

Implementation, security scan, extraction, checksum verification, documentation, and final review are recorded in `verification.md`.
