# Task Plan: local AI authoring and storage recovery

Restore local Scenario Studio AI authoring and document uploads using the approved Gemini profile
and canonical MinIO service. Configure the missing environment gates/credentials, restart exactly
one current-workspace web/runtime-worker pair, and verify both live paths.

Credentials remain environment-injected. AI output stays candidate-only. Storage verification uses
a random tenant-prefixed object and removes only that object. No database reset, release promotion,
or existing object deletion is included.

Rollback AI authoring by unsetting `AI_AUTHORING_MODEL_PROFILE_ID`; roll back host runtime state by
stopping the restarted processes. Existing bucket data and immutable profile/audit history remain.

Implemented and verified on 2026-07-16. See [verification](verification.md).
