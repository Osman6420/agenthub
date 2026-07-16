# Verification: phase-2-5-part-7-governed-transform-retrieval-dsl

## Delivered contract

- Immutable `transform_profile`, `chunking_profile` and `retrieval_profile` v1 schemas.
- Exact-key closed transform registry with bounded conditions and JSON Pointers.
- Deterministic copied-input executor with pre/post-step byte, record, string and time budgets.
- Validated bounded chunking and retrieval runtime projections.
- Runtime retrieval revalidation, server-owned ACL intersection and score-threshold enforcement.
- Stable content-free validation failures and release-compile defense in depth.

## Verification matrix

| Check | Result | Evidence |
| --- | --- | --- |
| Focused artifact/compiler | Passed | 19 passed |
| Focused executor/orchestration/retrieval | Passed | 44 passed, 8 PostgreSQL-only skipped |
| Full SQLite | Passed | 692 passed, 29 PostgreSQL-only skipped in 37.66s |
| Full PostgreSQL/RLS/pgvector | Passed | 716 passed, 5 SQLite-only skipped in 109.96s |
| Ruff | Passed | Format and lint clean |
| mypy | Passed | 358 source files clean |
| Django system check | Passed | No issues |
| Migration drift | Passed | No changes detected |
| compileall/diff check | Passed | Python compilation and final whitespace check clean |

## Security and authorization evidence

Negative tests cover unknown operations/keys, code-shaped fields, dangerous pointer segments,
expression depth, retrieval authority fields, invalid weights/top-k and record budgets. Retrieval
scope still comes only from signed execution context, exact release pins and durable consumer ACLs;
the normalized profile cannot supply tenant, consumer, index or document-set authority.

## Data, privacy and observability evidence

Execution deep-copies input, preserves explicit source identity, is deterministic and returns safe
codes without reflecting record values. No raw transform input/output was added to application logs
or audit metadata. Immutable artifact creation and existing release compilation retain their current
audited lifecycle.

## Migration evidence

`artifacts.0004_alter_artifactversion_type` additively exposes `transform_profile` in Django model
choices. It changes no table shape, tenant lineage, immutable artifact data or RLS policy.

## Manual review

Authenticated Turkish owner review of authoring guidance and candidate-versus-active wording is a
separate acceptance gate. No new graphical DSL editor was introduced.

## Final status

Implemented and automated-verified; authenticated Turkish owner browser review pending.
