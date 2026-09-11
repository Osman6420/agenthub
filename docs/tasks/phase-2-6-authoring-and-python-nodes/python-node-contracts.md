# P2.6.8 Python Node Review Contracts

## Contract versioning and checksum

All examples are design contracts, not implemented APIs or models. Canonical JSON uses UTF-8,
sorted object keys, no insignificant whitespace and JSON-native numbers. Arrays with set semantics
(`requested_modules`, finding summaries) are deduplicated and sorted before hashing. Checksums use
`sha256:<lowercase-hex>` and include the contract version.

`revision_checksum` covers:

```json
{
  "contract_version": "python-node-revision/v1",
  "source_utf8_lf": "def run(input, config): ...",
  "requested_modules": ["decimal"],
  "config_schema": {},
  "input_schema": {},
  "output_schema": {}
}
```

Line endings are normalized to LF; a UTF-8 BOM, invalid UTF-8, duplicate JSON keys and non-finite
numbers are rejected. Any change creates a new immutable revision and invalidates downstream
security review, human review and activation.

## Data contract

| Record | Mutable | Required bindings | Authority |
| --- | --- | --- | --- |
| `PythonNodeDraft` | Yes, optimistic `draft_revision` | organization/project/scenario, author, source and schemas | Authorized scenario author |
| `PythonNodeRevision` | No | draft lineage, server revision, source/schema/module checksums, source locator | Submission service |
| `PythonNodeSecurityReview` | No | revision checksum, rule-set checksum, image digest, report checksum | Automated review service |
| `PythonNodeReview` | No, decisions append | revision + security-report checksum, reviewer, decision | Assigned platform reviewer |
| `PythonNodeActivation` | No, events append | approved review + exact revision/report checksums | Platform activator |
| `PythonNodeTestRun` | No | exact revision/report/image and synthetic request checksum | Authorized author/reviewer |

Every row carries direct organization lineage. Cross-record database constraints and service locks
must prevent cross-tenant or stale binding. Request bodies never supply organization, project,
scenario, reviewer, revision number, activation state or source locator authority.

## Lifecycle invariants

```text
draft --submit--> submitted revision --security pass--> reviewable
reviewable --request changes/reject--> terminal decision
reviewable --approve--> approved --explicit activate--> active
active --disable--> disabled
disabled --new explicit activation decision--> active (only if policy still valid)
```

- Author and reviewer must differ. Review and activation are distinct explicit actions.
- Security `blocked` or `error` cannot become approved. Warnings require bounded rationale.
- A newer rule-set does not rewrite history. Policy may require re-review before a new activation or
  release; runtime always pins the report/rule-set accepted at activation.
- Disable blocks new save/publish/compile/run and not-started queue items immediately. Started work
  follows ADR-0011; emergency kill is separate.
- Required lifecycle audit is transactional/fail-closed and content-free.

## Automated rule-set v1

Initial stable finding families:

| Code family | Default severity | Meaning |
| --- | --- | --- |
| `PY_PARSE_*` | critical | Invalid/ambiguous syntax or encoding |
| `PY_BOUND_*` | critical | Source/schema/depth/module count exceeds policy |
| `PY_IMPORT_*` | critical | Dynamic, relative or non-allowlisted import |
| `PY_DYNAMIC_*` | critical | `eval`, `exec`, `compile`, dynamic code/import |
| `PY_REFLECT_*` | critical | Dunder/reflection/global frame/object graph access |
| `PY_IO_*` | critical | Filesystem, device, environment or raw stream access |
| `PY_PROCESS_*` | critical | Process, fork, thread, signal or native loading |
| `PY_NETWORK_*` | critical | Socket, HTTP, DNS or IPC/network primitive |
| `PY_SERIALIZE_*` | critical | Unsafe pickle/marshal/shelve-style deserialization |
| `PY_SCHEMA_*` | critical | Invalid/non-closed config/input/output contract |
| `PY_COMPLEXITY_*` | warning | Reviewability/complexity threshold exceeded |
| `PY_PROBE_*` | critical | Isolation/resource probe failed or was unavailable |
| `PY_SCANNER_ERROR` | critical | Rule execution incomplete; fail closed |

The platform-owned initial stdlib allowlist is intentionally not frozen by this branch. The runtime
owner must propose the smallest modules required by approved scenarios, with `decimal`, `math`,
`statistics`, `datetime`, `re`, `json` and `collections` evaluated individually. Allowlisting a
module never bypasses forbidden attribute/call rules. `os`, `sys`, `subprocess`, `socket`,
`multiprocessing`, `threading`, `ctypes`, `importlib`, `pathlib`, `shutil`, `tempfile`, `pickle`,
`marshal`, `shelve`, `urllib`, `http`, `ssl` and native extensions start denied.

The machine-readable content-free report is defined by
`fixtures/python-node-security-review-report.schema.json`.

## Source storage, retention and view options

| Decision | Option | Assessment |
| --- | --- | --- |
| Storage | Protected PostgreSQL text/byte field | Transactional and simple; DB backup/replica blast radius includes source |
| Storage | Private content-addressed object + PostgreSQL locator | Recommended; isolates source and supports lifecycle, but requires KMS/object-store approval |
| Encryption | Storage-provider only | Minimum infrastructure encryption; broad platform operator visibility may remain |
| Encryption | Envelope encryption with KMS per environment | Recommended; rotation/audit complexity and key service dependency |
| View roles | Platform admin implicitly | Rejected as default: too broad and hard to audit as a distinct purpose |
| View roles | Assigned `python_node_source_reviewer` + author own scope | Recommended; new authorization predicate requires owner approval |
| Retention | Delete on disable | Rejected: breaks review/release/run lineage |
| Retention | Policy/pin/legal-hold aware | Recommended; proposed periods in ADR-0011 need data-owner approval |

## Public catalog contract for P2.6.9

`fixtures/python-node-public-catalog.schema.json` is the only cross-lane contract from P2.6.8 to
P2.6.9. It is a tenant/scenario-authorized, stable-ordered response. Consumers must reject unknown
`contract_version`; unknown fields are forbidden to prevent accidental disclosure.

For Python nodes, only active exact revisions appear. `node_ref` is opaque and may be selected only
from the returned snapshot and revalidated live. Schema summaries are bounded closed JSON Schemas,
not source-derived prose. Managed nodes use the same envelope with `execution_class: managed` and
retain current compatibility.

Explicitly excluded: source/source checksum where not needed, requested modules, findings, review
rationale/identity, draft/pending/rejected metadata, test data, storage locator, runner endpoint,
image/runtime details, organization/project IDs, credentials and authorization policy.

## Required owner approvals before implementation

1. Security/platform: shared-kernel minimum runner, target seccomp/LSM/network proof and stronger
   sandbox trigger.
2. Authorization/product: author, assigned source reviewer, activator, organization-admin and
   auditor action matrix; separation of duties and source viewing.
3. Data/privacy: object store, KMS/envelope encryption, retention/legal hold/purge and backup scope.
4. SRE/platform: runner control plane/queue topology, image ownership, quotas, kill switch,
   reconciliation, SLOs and capacity.
5. API/architecture: any operator API, runner protocol or public catalog publication beyond this
   inert schema.
6. Dependency/supply chain: any scanner, gVisor, Kata, microVM runtime or new image/service.

## P2.6.8 runtime branch prerequisites

- ADR-0011 accepted with the approvals above and target-runtime spike evidence.
- P2.6.1 typed mapping/protected-key contract merged and verified.
- Exact lifecycle/report/catalog schemas reviewed by P2.6.9 and integration owners.
- Migration numbers and shared compiler/runtime seams allocated by the integration owner.
- Dedicated disabled-by-default authoring/test/runtime flags and kill-switch design approved.
- Runner image digest, rule-set checksum, module allowlist, budgets and patch owner frozen.
- No execution implementation begins in the application processes or by reusing the Compose app
  anchor.
