# Verification: Builder node configuration parity

## Implemented contract

- Configurable: `generate` (`prompt_ref`, `model_profile_ref`), `format_output`
  (`template_ref`), `condition`, `tool`, and `custom`.
- No config by compiler contract: `input`, `retrieve`, `validate_contract`, and `end`.
- Optional blank fields are omitted from graph config; required fields retain their visible empty
  placeholder until the author supplies a value and backend diagnostics accept it.
- Tool endpoints, secrets and foreign-tenant bindings remain absent from the node-schema response.

## Verification evidence

| Check | Result |
| --- | --- |
| Frontend Vitest | 20 passed |
| Frontend TypeScript/Vite build | Passed; 204 modules transformed |
| Builder/workflow focused pytest | 73 passed |
| Ruff | Passed |
| mypy | 358 source files clean |
| Django system check | No issues |
| Migration drift | No changes detected |

The focused pytest command was run without `-q` and without a pytest timeout. The immediately prior
committed baseline also passed the full SQLite and PostgreSQL/RLS suites; this follow-up changes
only server-owned UI schema projection, frontend serialization and their tests.

## Final reviews

- Staff engineer: the UI now matches existing compiler/runtime behavior and introduces no parallel
  node contract.
- Application security: manifest roles remain identifiers; endpoint/secret redaction and
  tenant-scoped tool/custom enumeration are unchanged.
- SRE: no migration, dependency, external call or runtime execution path changed.

## Manual evidence pending

Run manual row 2.26 after a hard refresh and confirm Turkish labels/layout for every node type.
