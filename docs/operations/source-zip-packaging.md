# Source ZIP Packaging

Use this workflow to hand off AgentHub application source together with the canonical OpenShift installation documentation. The ZIP is a source snapshot; it does not contain container images, credentials, environment-specific values, databases, object-store data, or Git history.

## Prerequisites

- Run the command from a Git checkout on Windows PowerShell 5.1 or PowerShell 7+.
- Review `git status --short` and decide whether non-ignored untracked files belong in the handoff.
- Keep secrets outside the repository. Use `.env.example` and Helm value examples only as schemas.

## Create a tracked-source package

```powershell
.\scripts\package-source.ps1
```

The default output is `dist/agenthub-source-<date>-<commit>.zip`. The script refuses to overwrite an existing file.

To include reviewed, non-ignored untracked files in a working-tree handoff:

```powershell
.\scripts\package-source.ps1 -IncludeUntracked
```

Use `-OutputPath` to choose a different file and `-Force` only when replacing that exact archive is intentional. An output inside the repository must remain below `dist/`; an absolute path outside the repository is also accepted.

## Contents and exclusions

Candidates come from Git-tracked files. `-IncludeUntracked` adds only files returned by `git ls-files --others --exclude-standard`. The workflow excludes:

- `.git`, virtual environments, dependency/build output, caches, and `dist`;
- `.env` variants other than `.env.example`;
- private-key and certificate-container extensions;
- local OpenShift environment/value files;
- SQLite, media, static collection, runtime, and local credential data.

Rooted/traversal candidates, symbolic links, and filesystem reparse points are rejected so package input cannot escape the checkout.

Each ZIP contains:

- source files below an `agenthub/` directory;
- `PACKAGE-README.md` with the source revision and installation entry point;
- `PACKAGE-MANIFEST.sha256` with a SHA-256 digest for every repository file in the package.

The primary installation path is `agenthub/docs/operations/openshift-helm-installation.md`. The lower-level `oc` path is documented in `agenthub/docs/operations/openshift-ubuntu-installation.md`, and the self-contained demo stack is documented in `agenthub/docs/operations/openshift-bundled-stack-helm.md`.

## Verify before distribution

Record the SHA-256 printed by the script, then inspect and extract the archive in a clean directory. Confirm the intended working-tree changes are present and no environment-specific files were added. Recipients should compare the ZIP digest over a separately authenticated channel.

This workflow does not sign or encrypt the archive. Use an organization-approved encrypted and authenticated transfer channel when source confidentiality matters.
