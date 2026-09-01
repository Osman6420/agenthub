# Threat Model: source-distribution-zip

## Assets

Application source, deployment definitions, installation documentation, local credentials, environment values, and generated package integrity.

## Actors

Package creator, authorized recipient/operator, and an unintended recipient of a leaked archive.

## Entry points

Script parameters, Git file inventory, working-tree files, temporary staging directory, and output ZIP path.

## Trust boundaries

The developer workstation and repository cross into a portable archive that may leave the workstation. Environment secrets and runtime data must remain outside that boundary.

## Data classifications

Source and documentation are internal distribution material. Tokens, passwords, private keys, environment overlays, DB/object-store contents, and Git metadata are confidential and excluded.

## Authentication

Not applicable to local archive creation. Distribution-channel authentication is outside this task.

## Authorization

The script does not grant access. The operator remains responsible for distributing the archive only to authorized recipients.

## Tenant isolation

No tenant data is read or packaged. Runtime databases, media, and object-store data are excluded.

## External systems

Git and local .NET ZIP support only; there are no network calls.

## Abuse cases

- A user attempts to package `.env`, private keys, environment-specific values, or repository history.
- A malicious path escapes the staging root.
- An existing ZIP is overwritten unexpectedly.
- Unreviewed untracked files enter a handoff.

## Failure cases

- Git is unavailable or a candidate disappears during packaging.
- The output is inside an included path and recursively packages itself.
- Archive creation is interrupted and leaves staging data.
- Recipient receives a corrupt or modified archive.

## Logging and audit risks

Console output must not print file contents or credentials. The archive README and manifest expose filenames and source revision by design.

## Mitigations

- Derive candidates from `git ls-files`; include non-ignored untracked files only with an explicit switch.
- Reject rooted/traversal paths, symbolic links/reparse points, and sensitive names/extensions; exclude generated, runtime, VCS, cache, and output trees.
- Require repository-local output to remain below `dist/` so a generated archive cannot enter a later package.
- Refuse to overwrite unless `-Force` targets the exact output file.
- Stage below a unique temporary directory and remove it in `finally`.
- Emit archive and per-file SHA-256 digests.
- Scan and extract-test the completed ZIP before distribution.

## Residual risks

Sensitive literal values embedded in otherwise legitimate tracked source or documentation require human/content scanning. SHA-256 provides integrity comparison, not signer identity or confidentiality.

## Required security tests

- Forbidden-entry scan across ZIP paths.
- Required-file allowlist assertions.
- Manifest checksum verification after extraction.
- Manual review of the final candidate list and repository diff.
