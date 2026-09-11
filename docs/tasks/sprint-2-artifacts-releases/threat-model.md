# Threat Model: sprint-2-artifacts-releases

## Assets

- Versioned artifact bodies (prompts, policies, contracts, profiles) and their
  integrity/immutability.
- Compiled releases and the active-release pointer that determines runtime behavior.
- GitOps import path (untrusted YAML entering the control plane).

## Trust boundaries

- Git repository / operator YAML → `import_gitops` → control-plane database.
- Operator/console → compile/promote actions.
- Application → PostgreSQL (tenant rows in one database; scope enforced in code).

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Secret committed inside an artifact/GitOps file | Inline-secret scanner rejects bodies whose secret-like keys hold non-`secret:` values; only `secret:<name>` references are allowed. Enforced on create and import; covered by tests. |
| Artifact tampering after review | `ArtifactVersion` is immutable (save rejects updates), checksummed with canonical JSON; releases pin exact versions + a manifest SHA-256. |
| Release references another tenant's artifact | Compiler resolves references only within the scenario's organization; cross-tenant reference fails compilation. |
| Two active releases / ambiguous runtime behavior | DB partial unique constraint (one active release per scenario); promotion runs in a transaction. |
| Malicious/oversized GitOps YAML (billion laughs, huge files) | `yaml.safe_load` only; size/structure validated; unknown types rejected before persistence. |
| Schema-invalid contract slips into a release | Contracts validated as JSON Schema at artifact creation and again at compile; invalid → compile error. |
| Privilege misuse (unauthorized promote) | Promotion/compile are role-gated (release_manager) and audited. |

## Residual risk

- Inline-secret detection is heuristic (denylist + reference form); a novel secret
  shape could evade it. Mitigated by keeping `secret:<name>` the only accepted form
  and by secret scanning in CI (planned). Reviewers still inspect artifact diffs.
- Full promotion/canary/rollback and evaluation gates are not yet present; releases
  compiled here are candidates and must not be treated as production-active until
  Sprint 6 adds the gated promotion path.
