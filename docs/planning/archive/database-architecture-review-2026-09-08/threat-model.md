# Review boundaries and risks

Assets: tenant-owned content, version pins, runtime checkpoints, authorization grants, credential references and audit history. Actors: operators, consumers and background workers. Boundaries: tenant RLS, server-side capabilities, immutable releases, connector/provider profiles, object storage and queue delivery.

This task reads source and local schema/aggregates only. It does not query content or secret fields, contact providers, mutate live data, or modify policy. Recommendations must retain relational integrity, tenant checks, retries/idempotency, approval evidence and recoverability. Removing an apparently unused table requires deployment-wide usage and retention evidence plus an approved migration task. Local emptiness is insufficient. Residual risk: static references and development data cannot prove all deployed usage or production workload behavior.
