# Proportional security and operational design review

No system behavior is changed by this task. Protect source files and unrelated working-tree changes. Read no document content, secret values or production data.

For the target design, separate security invariants (authenticated actor, server-owned scope, approved egress destinations, secret handling, authorized retrieval and tools, bounded workloads, safe audit and deletion) from optional governance policy (role granularity, author/approver separation, release gates, immutable named artifacts and manual index promotion). Simplification of policy must not silently remove enforcement.

Evaluate tenant/workspace leakage, source-ACL mismatch, document prompt injection into tool calls, externally supplied URLs/SQL, MCP identity/token boundaries, tool side effects and uncertain retries, partial indexing, stale workers, config races, credential rotation/revocation, retained sensitive responses, rollback to revoked resources and replay of writes. Describe where each remains enforced in a smaller design.

Residual risks are design-level: target implementation is unbuilt, owner scope partly open, external connector API contracts vary, and no benchmark demonstrates the performance/capacity of proposed vector storage. Publishing snapshots cannot guarantee exact output reproduction from mutable external models or REST/MCP sources.
