# System Overview

## Verified current system

As of 2026-07-10, the repository contains design documents only. No executable application, runtime configuration, schema, CI/CD, or deployment artifact is present. Therefore no running component, flow, or external dependency can be asserted.

## Target architecture (not implemented)

[`agenthub-v3-django-plan.md`](../../agenthub-v3-django-plan.md) proposes a Django modular monolith whose processes expose HTTP/MCP gateway functions and run Celery-backed ingestion, evaluation, workflow, and agent work. Proposed boundaries include control plane, gateway, RAG runtime, ingestion, workflow/agent runtime, tool proxy/approval, evaluation/release, and audit. Proposed external dependencies include PostgreSQL/pgvector, Redis, object storage, identity/model providers, and OpenShift.

Major proposed flow: trusted ingress authenticates a consumer, resolves tenant/scenario capability, and creates an execution context; the pinned release drives RAG/workflow/agent execution; tool access passes through a controlled proxy; state changes and security decisions produce audit events. This is a design summary, not evidence of implementation.

## Assumptions requiring confirmation

- The v3 document is the authoritative target over the v2 RAGaaS documents.
- A modular monolith remains the intended initial deployment boundary.
- External providers and operational ownership have not yet been selected.

Update this document only from implemented code/configuration and verified runtime behavior. Record durable deviations from the target in ADRs.
