# Verification: phase-2-6-part-9-studio-authoring-context

## Status

**Verified for the Phase 2.6 scope.** Studio AI receives a deterministic, bounded and
tenant/scenario-scoped capability snapshot; generated references are checked against that snapshot;
generation remains transient; and a missing Python capability opens only an editable browser-memory
scaffold. The scaffold cannot create code, a database row, review, approval or activation.

P2.6.8 is consumed through an optional, fail-closed public catalog provider. The provider accepts
only exact safe metadata fields and rejects Python source or any additional field.

## Implemented evidence

- Safe authoring context now includes exact workflow/node contracts, managed and Python node public
  catalogs, tool role description/approval/risk metadata, active/candidate prompt/model/retrieval
  roles, bounded input/output schemas, document-set retrieval readiness, release lifecycle and draft
  revision metadata.
- Python catalog fields are exact-allowlisted, schemas are depth/property bounded, entries are
  deterministically ordered and the total canonical context retains its byte budget and checksum.
- Tool endpoints, binding credentials, Python source and document contents are not serialized.
- Generated tool, managed/Python node, prompt and model references fail closed when absent from the
  exact context snapshot.
- `capability_missing` produces an editable Turkish-first Studio scaffold only. It is explicitly
  transient and does not bypass the future author draft → test → review → activation lifecycle.
- Existing transient candidate, diagnostics, explicit save/update/copy, lineage and optimistic
  concurrency behavior remains unchanged.

## Automated verification

The repository `.venv` launcher is Microsoft-Store-backed and failed before Python start with
`A specified logon session does not exist`. Per the manual testing guide, Python checks used a
disposable `python:3.13-slim` container mounted to this worktree. No production data, secret or live
AI provider was used.

| Check | Result |
| --- | --- |
| Focused SQLite authoring/context tests | **9 passed** |
| Focused PostgreSQL/pgvector authoring/context tests | **9 passed** |
| Frontend Vitest suite | **7 files, 20 tests passed** |
| TypeScript + Vite production build | **Passed** |
| Ruff format/check (`apps/builder`, settings) | **Passed** |
| mypy (`apps`) | **Passed**, 385 source files |
| Django system check | **Passed** |
| Migration drift | **Passed**, no changes detected |
| Python compileall | **Passed** |
| `git diff --check` | **Passed** |

Focused tests cover deterministic redacted context, safe Python-node catalog integration, rejection
of non-public/source fields, input contract and release-role exposure, document-set capability
summary, and invented tool/prompt/model reference denial. Existing authoring tests cover transient
generation and save behavior.

## Security, authorization and privacy review

- Context lineage is checked server-side and every query remains organization/scenario scoped.
- The model and browser do not gain authority from user text or catalog descriptions.
- The Python provider is a server-configured adapter, not a client-supplied import path.
- Secret values, endpoints, Python source and document contents remain outside context and audit.
- No authentication, role grant, public API, production dependency or network authority changed.

## Checks not run

- Full repository SQLite/PostgreSQL regression is deferred to the 7/8/9/10 integration merge gate;
  focused SQLite and PostgreSQL profiles pass here.
- Browser-driven manual Studio testing was not repeated on this branch; component tests and the
  production bundle cover the new callback/scaffold seam. Integration browser review remains part
  of final Phase 2.6 acceptance.
- No live model call was made; model behavior is exercised through deterministic provider fixtures.

## Residual risks

- The public Python-node provider is an integration seam until P2.6.8's durable author/review
  control plane supplies active tenant-authorized rows. An unset provider advertises no Python
  nodes; malformed or source-bearing output fails closed.
- The missing-capability scaffold is intentionally memory-only. Transfer into a durable custom-node
  draft waits for the approved P2.6.8 control-plane API and must preserve normal review/activation.
- Frontend tests emit one existing React `act(...)` warning although all assertions pass.

## Final review

- **Staff engineer:** bounded adapters reuse current artifacts, releases, documents and identifier
  flows without new persistence or public contracts.
- **Application security:** safe-field allowlists, tenant lineage, bounded schemas, exact reference
  validation and non-bypass lifecycle behavior were reviewed.
- **SRE:** no migration, service topology or runtime authority changed; malformed provider/context
  data fails closed with deterministic errors.
