# P2.6.0 Enterprise Scenario Contract Corpus

These are target contract fixtures, not importable workflow artifacts. They intentionally avoid a
complete `agenthub/v1` JSON body until the owning primitive is implemented. Each scenario must later
gain compiler-valid JSON and executable eval fixtures in its owning branch.

## Common trajectory requirements

Every scenario must prove: happy path, invalid input, authentication failure, authorization denial,
cross-tenant denial, timeout, cancellation, replay/redelivery, partial failure, stale revision or
resume, budget exhaustion, audit/redaction and crash/restart recovery.

## S01 — Regulatory evidence and exception decision

- **Purpose:** collect governed document evidence, validate citations, route exceptions to a human
  decision and publish a bounded evidence package.
- **Capabilities:** retrieval, parallel evidence collection, deterministic join, human task,
  contract validation.
- **Input intent:** tenant-scoped case reference and approved query fields.
- **Output intent:** decision status, cited evidence references and safe reason codes.
- **Critical denials:** foreign document set, self-approval where separation of duties applies,
  forged/replayed decision, uncited final output.
- **Recovery:** expiry/escalation, worker restart while waiting, late decision after cancellation.

## S02 — Human-approved infrastructure change

- **Purpose:** plan a bounded change, obtain approval, execute through a pinned tool, verify outcome
  and compensate or escalate safely.
- **Capabilities:** tool approval, wait/resume, verify, error routing and compensation.
- **Critical denials:** model-selected endpoint/tool, requester self-approval, substituted tool input
  after approval, automatic retry/rollback on `outcome_unknown`.
- **Recovery:** crash before/after external call, duplicate task, verification failure, manual
  reconciliation and compensation failure.

## S03 — Procurement exception with separation of duties

- **Purpose:** evaluate policy and evidence, collect finance and compliance decisions, then emit an
  immutable recommendation.
- **Capabilities:** parallel human tasks, threshold/all join, expiry/escalation and audit.
- **Critical denials:** same actor satisfying incompatible roles, foreign-project purchase request,
  decision checksum mismatch and post-decision payload mutation.
- **Recovery:** one approver timeout, rejection racing approval, cancelled request with late resume.

## S04 — AML/fraud evidence fan-out

- **Purpose:** query independent governed evidence sources concurrently and synthesize after a
  deterministic threshold/all/fail-fast policy.
- **Capabilities:** bounded `for_each`, parallel branches, deterministic join and retrieval/tool
  mappings.
- **Critical denials:** unbounded entity list, branch writing protected/shared keys, foreign-tenant
  evidence and implicit last-writer-wins merge.
- **Recovery:** branch timeout, duplicate/late result, partial threshold completion, worker loss and
  total state-budget exhaustion.

## S05 — Data-governance/PII remediation

- **Purpose:** identify governed records, propose remediations, require approval for side effects,
  verify and produce an audit-safe report.
- **Capabilities:** retrieval, bounded collection, Python/managed transform where approved, tool
  action, human task and compensation.
- **Critical denials:** secret/PII leakage to model context or logs, unapproved Python revision,
  direct filesystem/network access and cross-tenant record mutation.
- **Recovery:** disabled node revision, partial remediation, ambiguous external outcome and manual
  recovery without replaying completed side effects.

## S06 — Incident observe-act-verify loop

- **Purpose:** collect observations, propose a governed action, obtain approval when required,
  execute, verify and either conclude or escalate within hard limits.
- **Capabilities:** structured agent decision, retrieval/tool actions, approval, bounded replanning,
  verification and escalation.
- **Critical denials:** invented tool/ref, prompt-injected capability, repeated side effect, budget
  amplification and hidden authorization data in planner context.
- **Recovery:** provider timeout/rate limit, repeated-action detection, inconclusive verification,
  `outcome_unknown` and kill-switch activation.

## S07 — Contract review composition

- **Purpose:** run pinned clause extraction and risk-review child workflows/agent calls and combine
  schema-constrained results.
- **Capabilities:** sub-workflow/agent call, attenuated roles, depth/call budgets and output mapping.
- **Critical denials:** foreign-tenant child, latest/unpinned resolution, recursive cycle, child tool
  outside effective capability intersection and full parent-state disclosure.
- **Recovery:** child timeout/cancellation, parent cancellation with late child result, incompatible
  child revision and partial child failure routed through explicit policy.

## Ownership mapping

| Scenario | Primary owning parts |
| --- | --- |
| S01 | P2.6.1, P2.6.2, P2.6.3, P2.6.11 |
| S02 | P2.6.3, P2.6.4, P2.6.6 |
| S03 | P2.6.2, P2.6.3, P2.6.11 |
| S04 | P2.6.1, P2.6.2, P2.6.11 |
| S05 | P2.6.1, P2.6.3, P2.6.4, P2.6.8 |
| S06 | P2.6.4, P2.6.6, P2.6.11 |
| S07 | P2.6.4, P2.6.5, P2.6.6 |
