# Verification — authorization simplification assessment

Date: 2026-09-09. Scope: source assessment against the current local working tree,
including pre-existing uncommitted changes. No application implementation.

## Discovery and evidence

- Tool metadata search found no Codebase Memory or Serena tools. Used direct reads,
  `rg --files`, exact `rg -n` searches and existing tests as instructed fallback.
- `git status --short` recorded an already dirty working tree across console,
  documents, evaluations, gateway, ingestion, releases, tools, frontend and docs.
  The assessment did not edit those application files or rely on stale handoff runtime claims.
- Read root `AGENTS.md`, engineering rules, task README/templates, handoff,
  planning archive policy, master plan, ADR-0015 and relevant migration declarations.
- Read capability enums, authorization maps, assignment mutations, membership
  compatibility helpers, consumer binding/token paths and scoped querysets.
- Exact symbol/literal searches covered `TOOL_APPROVE`, `MEMORY_READ`,
  `MEMORY_WRITE`, `INGESTION_TRIGGER`, `RELEASE_PROMOTE` and lowercase forms in
  production source, excluding tests, migrations, docs and generated outputs.
  No active consumer checks found for those five values. `INGESTION_TRIGGER`
  remains in the console preset; release console operations use human authority.
- Read gateway admission, MCP operations, document content and retrieval grants,
  tool proxy/approval, child attenuation, agent policy, RLS middleware/migration,
  connector grant services, builder API and frontend bootstrap/controller.
- Read targeted tests and relevant pre-existing diff statistics.
- Parsed both capability classes using Python AST: human 24, consumer 10.
  Read model declarations: 1 platform + 2 organization + 2 project + 5 scenario
  + 3 document-set responsibilities = 13 named responsibilities.
- Verified `roles.py` does not appear as an imported authority in the searched
  production apps/config source; this is not proof about external integrations.
- Read OWASP Authorization Cheat Sheet (2026-09-09) as primary-source support for
  per-request server enforcement, not for a mandatory role count.
- Several exploratory reads targeted nonexistent guessed paths, and three reads
  accidentally used spelled-out line counts. These failed without mutation;
  relevant actual files/counts were subsequently resolved and read. No conclusions
  depend on those failed reads. No missing code-intelligence output was inferred.

## Executed tests

Repository `config.settings.test` explicitly uses in-memory SQLite, local memory
cache/object store and eager Celery; no live service startup or database reset.

```powershell
.venv/Scripts/python.exe -m pytest apps/identity/tests/test_responsibility_authorization.py apps/identity/tests/test_operator_authorization.py apps/identity/tests/test_binding.py apps/builder/tests/test_responsibility_authorization.py apps/console/tests/test_responsibility_access_console.py apps/documents/tests/test_scenario_access.py apps/tools/tests/test_scenario_approval_authorization.py apps/mcp/tests/test_mcp.py -q
```

Result: **43 passed in 19.97s**, exit 0. Covers membership-only denial,
administrator/content separation, exact scenario scopes, assignment expiry,
consumer bindings, builder reads/writes, document access and MCP/tool approval.
It does not prove every authorization path or the proposed replacement model.

From `frontend/`:

```powershell
npm.cmd test -- --run src/__tests__/flow.test.tsx src/__tests__/app_deeplink.test.tsx src/__tests__/artifact_draft_editor.test.tsx
```

Result: **3 files / 15 tests passed**, exit 0, duration 1.30s. Includes controller
read-only behavior; does not substitute for a live browser gate.

## Not run / assumptions

No full backend suite, full frontend suite/build, formatter/linter/type checker,
secret/dependency/container scanner, migration drift test, PostgreSQL RLS suite,
live browser tests or live credential/provider access. This task changes only
documentation and makes no deployment claim. Those checks remain applicable to
any subsequent authorization implementation; PostgreSQL-only isolation is not
verified by SQLite tests.

Actual customer roles, compliance separation, deployment data and end-user
identity propagation were not inspected. The MCP ingestion scope finding is a
source-review result; no new regression test or live exploit reproduction was run.

## Final review

- Staff-engineer review: central capability service is useful; product role
  packages can simplify administration. Proposed inheritance is clearly separate
  from existing additive exact assignments. Actor classes and operation scopes
  remain distinct. Old roles cannot map automatically to broader manager roles.
- Application-security review: preserve content/retrieval separation, server-side
  trusted target validation, human approval, tenant boundaries, revocation,
  expiry, consumer ownership, child attenuation and audit. Flag MCP status scope.
- SRE review: no runtime restart or migration required. Existing dirty work
  preserved. Future rollout needs worker/cache/policy version coordination and
  access-difference evidence; no production effectiveness claim made here.

## Documentation closure

Assessment archived under its stable dated identifier. Master plan and archive
index receive links describing assessment completion only. Final relative-link,
UTF-8 and whitespace validation results are recorded at closure below.

- Python validation: all 4 new Markdown files decode as UTF-8 without replacement
  characters, end with a newline, and contain no trailing whitespace; all 20
  relative file links resolve. PASS.
- `git diff --check -- docs/planning/master-plan.md docs/planning/archive/README.md`:
  exit 0. Reviewed added assessment links alongside the existing owner edits;
  retained the earlier project/scenario boundary clarification unchanged.
- Archive move validated resolved source/destination as descendants of the local
  docs root, required a nonexistent destination, and moved only this assessment.
- No application file, permission assignment, dependency, migration or runtime
  setting was modified by this assessment. No commit or push was made.
