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
- Node: `{"id":"...","type":"...","config":{...}}`; empty `config` may be omitted. Mapping-eligible
  nodes may add optional `input_mapping`/`output_mapping` (see "Typed state mapping").
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
- `tool`: required `binding_role` (a release-pinned tool-binding role). Provide the input as either a
  legacy `input_key` **or** an `input_mapping` (never both), and the output as exactly one of a legacy
  `output_key` **or** an `output_mapping`.
- `custom`: required `node_ref`, optional `fields`. Use only platform-registered node refs supplied
  by the operator; never invent packages or executable code.
- `transform`: exactly `{"transform_profile_ref":"..."}`, a release manifest role that pins an
  immutable `transform_profile` artifact (the closed governed operation registry). It carries no
  inline operations, expressions or templates and **requires** both `input_mapping` and
  `output_mapping`.
- `agent_loop`: canonical governed agent execution. Config requires `tool_binding_roles` and may contain only
  `retrieval`, `limits`, `objective_key`, `output_key`, `system_prompt`, and `actions`. It requires
  both mappings. Tool roles are release roles, never endpoints, secrets or artifact IDs.

Allowed types: `input`, `retrieve`, `generate`, `condition`, `format_output`,
`validate_contract`, `tool`, `custom`, `transform`, `agent_loop`, `parallel`, `for_each`, `join`,
`subworkflow`, durable wait nodes, and `end`.

## Typed state mapping

`retrieve`, `generate`, `tool`, `custom` and `transform` nodes may declare typed mappings that move
data between run-state locations. There is no expression, template or code — only explicit copies.

- `input_mapping`/`output_mapping` are lists of `{"from":"<pointer>","to":"<pointer>"}` (max 24 each).
- Pointers are restricted absolute JSON Pointers, e.g. `/input/customer_id`. Root/empty pointers,
  URI fragments, wildcards (`*`), recursive descent (`**`), filters, array append (`-`) and negative
  indexes are forbidden; escapes are only `~0` (`~`) and `~1` (`/`); max 256 chars and 12 segments.
- When `input_mapping` is present the node sees **only** the fields it maps (a node-local envelope),
  not ambient state.
- `output_mapping` destinations may only write the business namespaces `/input`, `/retrieval`,
  `/branches`, `/evidence`, `/decisions`, `/output`. Writing any server-owned namespace (tenant,
  actor, authorization, capability, release, execution, secret, budget, audit, …) is rejected.
- Two entries may not target the same or an overlapping destination.

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
