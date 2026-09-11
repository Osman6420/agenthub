# Task Plan: workflow authoring guide unification

Keep the detailed architecture guide intact and add a purpose-built concise workflow Markdown as
the single text fed to governed AI authoring and both console copy surfaces.

The short guide contains only the current workflow document shape, graph invariants, exact node
configs, condition subset, safety restrictions, and one valid example. It is trusted repository
content, bounded to 12 KB, loaded fail-closed, and kept separate from the untrusted user message.
Planned transform DSL and unrelated artifact details are excluded.

No migration, public API, authorization, tenant, dependency, or persisted draft change is involved.
Implemented and verified on 2026-07-16. See [verification](verification.md).
