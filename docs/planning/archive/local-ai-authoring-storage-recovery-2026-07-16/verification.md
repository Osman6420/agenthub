# Verification: local AI authoring and storage recovery

- Canonical Compose MinIO/PostgreSQL/Redis: healthy.
- Application live/readiness: HTTP 200.
- Current workspace web and runtime/default Celery worker restarted with one pair only.
- Governed Scenario Studio `generate_candidate`: success; candidate diagnostics valid.
- MinIO `agenthub` bucket: present.
- Document storage put/get/delete: success; 22-byte random smoke object deleted afterward.
- Targeted hermetic builder/document tests: 66 passed.
- Docker Compose config and `git diff --check`: passed.

Root causes were missing `AI_AUTHORING_MODEL_PROFILE_ID`/`AI_AUTHORING_PROVIDER` and missing host-mode
MinIO endpoint/credential environment. No credential, candidate body, document content, or provider
response is recorded here.

Full suite, mypy, formatter, migration drift, PostgreSQL full suite, browser automation, and
production deployment checks were not run.
