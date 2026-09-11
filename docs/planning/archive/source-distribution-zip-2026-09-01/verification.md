# Verification: source-distribution-zip

| Check | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- |
| PowerShell syntax | PowerShell parser API over `scripts/package-source.ps1` | Pass | No parser errors | PowerShell 7 host |
| Package creation | `scripts/package-source.ps1 -IncludeUntracked` | Pass | 1,194 repository files packaged from commit `48f6bb36c076`; dirty state recorded | Current reviewed RLS-fix additions intentionally included |
| Required entries | .NET ZIP entry assertions | Pass | 11 required entries present | Includes Helm guide/chart, Dockerfile, package tooling, migration, and RLS verification |
| Forbidden paths | .NET ZIP path-pattern scan | Pass | Zero forbidden entries | Covers VCS, environments, caches, runtime data, secret/value names, and key/container extensions |
| Extraction | `.NET ZipFile.ExtractToDirectory` into unique OS temp directory | Pass | Clean extraction completed | Temporary directory removed in `finally` |
| Per-file integrity | Recompute SHA-256 for every manifest entry | Pass | 1,194/1,194 files matched | Package metadata files are intentionally outside the repository-file manifest |
| ZIP integrity | `Get-FileHash -Algorithm SHA256` | Pass | Final digest is emitted and reported with the delivered artifact | Digest is kept out of the ZIP to avoid self-reference |

## Acceptance criteria mapping

- Application source, charts, installation documents, packaging documentation, and the current untracked RLS migration/task evidence are present.
- Local secrets, environment values, Git history, runtime data, caches, dependencies, and build output are absent by candidate derivation and denylist scan.
- The archive extracts cleanly and every repository file matches `PACKAGE-MANIFEST.sha256`.

## Security requirement mapping

The path inventory is Git-derived; non-ignored untracked files require `-IncludeUntracked`; rooted paths, traversal, symlinks, and reparse points are rejected; repository-local output is constrained below `dist/`; known secret/runtime patterns fail closed; overwrite requires `-Force`; staging uses a unique validated OS temporary directory and is removed in `finally`.

## Authorization tests

Not applicable. No runtime authorization path changed.

## Cross-tenant tests

Not applicable. No runtime or tenant data is accessed.

## Logging and redaction tests

The script prints only package metadata, counts, paths, source state, and digests. It does not print file contents.

## Audit event tests

Not applicable. Local developer tooling does not emit application audit events.

## Migration verification

No migration was introduced by this packaging task. The separate staged-index migration is included as requested but owned and verified by its own task record.

## Behavior comparison with base branch

Application and deployment runtime behavior are unchanged. New behavior is limited to an opt-in local source-packaging command and documentation.

## Checks not run

- Application tests were not rerun because this task changes no application/runtime code; the included RLS fix retains its separate verification record.
- Malware/secret-scanner products and archive signing were unavailable; Git/path policy and manual diff/entry review were used.
- No live OpenShift install was run from the ZIP; cluster admission and environment configuration remain operator gates in the installation guide.

## Remaining risks

A sensitive literal embedded in a legitimate source/documentation file may evade filename-based controls. The ZIP is neither encrypted nor cryptographically signed. The snapshot is dirty and therefore must not be represented as a reproducible release.

## Human review required

Before external distribution, an authorized owner must review the recipient, transfer channel, final ZIP digest, working-tree scope, and any organization-required DLP/malware/signing checks.

## Final status

Completed. Implementation and local verification are complete; environment-specific distribution approval remains outside this task.
