# Assessment threat model

Assets: tenant/project/scenario isolation, protected document content, credentials,
runtime history, tool side effects, approvals and audit evidence.

Actors: human operators, administrators/recovery identities, API/MCP consumers,
workers and child workflow/agent runs. Browser flags are untrusted presentation;
machine identities must not substitute for verified human identity.

Boundaries: membership versus object authority; organization/project/scenario;
document retrieval versus source-content inspection; machine binding versus
release-pinned runtime policy; human approval versus execution identity.

Risk under simplification: implicit parent inheritance exposes previously private
children; merged editor/operator roles enable traffic changes; broad consumer
defaults unlock tools or memory; removing document grants leaks confidential
sources; trusting browser state bypasses server authorization; cached permissions
outlive revocation. Retain server checks, exact trusted targets, audit, negative
tests and explicit rollout mapping in any future implementation.

This task reads local source and runs isolated existing tests only. It does not
inspect live credentials/content, operate the application or alter permissions.
Actual role usage and organizational compliance requirements remain unverified.
