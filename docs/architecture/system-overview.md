# System Overview

## Verified current system

The repository contains an executable Django modular monolith. Foundation,
tenant/identity/catalog, artifact/release, gateway/ExecutionContext, and the
deterministic RAG runtime slices are implemented and verified. The authoritative
milestone status and evidence links are maintained in the
[master plan](../planning/master-plan.md).

## Target architecture

[`agenthub-v3-django-plan.md`](../../agenthub-v3-django-plan.md) defines the full
target. Later slices—including real ingestion/vector retrieval, external model
providers, evaluation gates, workflow/agent execution, tool proxy/approval, and
deployment manifests—remain planned unless the master plan records verification.

Major proposed flow: trusted ingress authenticates a consumer, resolves tenant/scenario capability, and creates an execution context; the pinned release drives RAG/workflow/agent execution; tool access passes through a controlled proxy; state changes and security decisions produce audit events. This is a design summary, not evidence of implementation.

## Versioning baseline

- The target document is revision 3; this revision number is not an AgentHub product/API version.
- The system is implemented as a greenfield AgentHub and has no runtime, build, or migration dependency on a v2 application or the archived RAGaaS documents.

## Assumptions requiring confirmation

- A modular monolith remains the intended initial deployment boundary.
- External providers and operational ownership have not yet been selected.

Update this document only from implemented code/configuration and verified runtime behavior. Record durable deviations from the target in ADRs.
