# AgentHub Workflow DSL — LLM Authoring Guide

Generate exactly one AgentHub workflow as JSON. Return only the JSON object: no Markdown fence,
explanation, endpoint, URL, credential, secret, executable code, Python, package, or entrypoint.

## Document shape

```json
{
  "api_version": "agenthub/v1",
  "kind": "Workflow",
  "metadata": {"id": "workflow-id"},
  "spec": {"input_node": "request", "nodes": [], "edges": []}
}
```

- Use exactly the keys shown. Maximum 50 nodes, 100 edges, and 64 characters per identifier.
- Node: `{"id":"...","type":"...","config":{...}}`; empty `config` may be omitted.
- Edge: `{"from":"...","to":"..."}`. Only condition edges may add boolean `when`.
- Node IDs are unique. `input_node` references an `input` node.
- The graph is acyclic; every node is reachable from input; at least one `end` is reachable.
- Every non-`end` node has an outgoing edge. An `end` node has none.

## Node types and exact config

- `input`, `retrieve`, `validate_contract`, `end`: no config.
- `generate`: optional `prompt_ref` and `model_profile_ref`. Values are release manifest role names,
  not `logical_id:vN` artifact references.
- `condition`: exactly `{"expression":"..."}`. Maximum 500 characters. Use only `and`, `or`,
  `==`, `!=`, `>`, `>=`, `<`, `<=`, constants, state root names, and dotted fields. Do not use
  `not`, subscripts, calls, arithmetic, or private names. Provide boolean `when: true` and
  `when: false` outgoing branches.
- `format_output`: `template_ref` is currently literal output text, not an artifact reference.
- `tool`: exactly `binding_role`, `input_key`, `output_key`; all are identifiers. `binding_role` is
  a release-pinned tool-binding role.
- `custom`: required `node_ref`, optional `fields`. Use only platform-registered node refs supplied
  by the operator; never invent packages or executable code.

Allowed types: `input`, `retrieve`, `generate`, `condition`, `format_output`,
`validate_contract`, `tool`, `custom`, `end`.

## Example

```json
{
  "api_version": "agenthub/v1",
  "kind": "Workflow",
  "metadata": {"id": "support-rag.v1"},
  "spec": {
    "input_node": "request",
    "nodes": [
      {"id": "request", "type": "input"},
      {"id": "retrieve", "type": "retrieve"},
      {"id": "answer", "type": "generate"},
      {"id": "validate", "type": "validate_contract"},
      {"id": "done", "type": "end"}
    ],
    "edges": [
      {"from": "request", "to": "retrieve"},
      {"from": "retrieve", "to": "answer"},
      {"from": "answer", "to": "validate"},
      {"from": "validate", "to": "done"}
    ]
  }
}
```

The backend validator/compiler is authoritative. This concise guide is derived from the detailed
[`artifacts-and-dsl-authoring-guide.md`](artifacts-and-dsl-authoring-guide.md); update both whenever
the current workflow contract changes.
