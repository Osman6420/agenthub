# Threat Model: Builder node configuration parity

## Trust boundaries and risks

The node form is untrusted browser input. The backend compiler remains authoritative. A schema
projection could leak tool destinations/secrets, offer foreign-tenant refs, serialize optional
empty identifiers that fail only at publish time, or claim support for fields ignored by runtime.

## Mitigations

- Derive fields only from current compiler/runtime behavior.
- Expose prompt/model values as manifest-role identifiers, not artifact bodies or endpoints.
- Keep tool/custom enums tenant-scoped and retain existing redaction tests.
- Omit blank optional fields and run canonical backend diagnostics before save/publish.
- Do not broaden compiler allowlists or runtime capability in this task.

## Required tests

Complete built-in node field matrix, optional-field omission, generate JSON round-trip, existing
tool/custom tenant isolation and endpoint/secret redaction, and no-config node preservation.

