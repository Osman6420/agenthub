# Agent Workflow Efficiency Threat Model

## Assets and trust boundaries

- Source code, tests, tenant-isolation and authorization controls.
- The boundary between the capable planning/review agent and the lower-cost
  implementation worker.
- Serena MCP, which can read and edit workspace files through semantic tools.

## Risks and mitigations

- **Worker makes an unplanned security decision:** worker instructions require it
  to stop; main agent retains all trust-boundary decisions and reviews the live diff.
- **Semantic edit changes unintended references:** require reference inspection,
  final diff review, and normal tests/static checks.
- **Parallel writers conflict:** permit only one implementation worker.
- **Worker assertion is mistaken:** explicitly disallow treating its report as
  evidence; main agent must independently verify.
- **MCP is unavailable or incomplete:** fall back to `rg` and ordinary file tools;
  never bypass validation.
- **Agent trusts stale runtime state or starts duplicate processes:** require the
  durable local runbook plus live Compose/health inspection before start or diagnosis.
- **Model routing increases rather than lowers cost:** keep use bounded and
  task-specific; do not set Fable or GPT-5.6 as an unconditional project default.

## Residual risk

Model aliases, availability, and tool-selection behavior can change between client
versions. The workflow needs a small real-task evaluation before being treated as
cost-optimal.
