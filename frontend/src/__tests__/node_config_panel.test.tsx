import { fireEvent, render, screen } from "@testing-library/react";
import type { Node } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";

import { NodeConfigPanel } from "../components/NodeConfigPanel";
import type { BuilderNodeData, NodeSchema } from "../types";

const schema: NodeSchema = {
  organization: "org",
  can_write: true,
  dsl: { api_version: "agenthub/v1", kind: "Workflow" },
  limits: { max_nodes: 50, max_edges: 100 },
  node_types: [{
    type: "generate", label: "Generate", category: "rag", fields: [
      { name: "prompt_ref", kind: "identifier", required: false },
      { name: "model_profile_ref", kind: "identifier", required: false },
    ],
  }],
  tool_binding_roles: [],
  custom_nodes: [],
  projects: [],
};

const compositionSchema: NodeSchema = {
  organization: "org",
  can_write: true,
  dsl: { api_version: "agenthub/v1", kind: "Workflow" },
  limits: { max_nodes: 50, max_edges: 100, max_parallel_branches: 16 },
  gates: { composition_enabled: false },
  retry_policy: {
    max_attempts: { min: 1, max: 3 },
    backoff_seconds: { min: 0, max: 300 },
    retry_on: ["transient"],
    idempotent_required: true,
  },
  node_types: [
    {
      type: "agent_call",
      label: "Ajan çağrısı",
      category: "composition",
      composition: true,
      supports_mapping: true,
      mapping_required: true,
      supports_retry: true,
      fields: [
        { name: "agent_role", kind: "identifier", required: true },
        { name: "max_decisions", kind: "integer", required: true, min: 1, max: 20 },
        {
          name: "allowed_actions",
          kind: "list",
          required: true,
          options: ["escalate", "respond", "retrieve", "tool", "verify"],
        },
      ],
    },
  ],
  tool_binding_roles: [],
  custom_nodes: [],
  projects: [],
};

describe("node config panel", () => {
  it("renders a gated composition node with integer, list and mapping editors", () => {
    const onChange = vi.fn();
    const onPatchData = vi.fn();
    const node = {
      id: "review",
      type: "builderNode",
      position: { x: 0, y: 0 },
      data: { nodeType: "agent_call", config: { max_decisions: 5 } },
    } as Node<BuilderNodeData>;
    render(
      <NodeConfigPanel
        schema={compositionSchema}
        node={node}
        disabled={false}
        onChange={onChange}
        onPatchData={onPatchData}
        onRemove={vi.fn()}
      />,
    );

    // Gated (composition disabled) note is shown but the node is still authorable.
    expect(screen.getByRole("note")).toBeInTheDocument();
    // Integer field carries its numeric value.
    expect(screen.getByLabelText("max_decisions")).toHaveValue(5);
    // Closed-option list renders as checkboxes; toggling emits the array.
    fireEvent.click(screen.getByLabelText("allowed_actions:verify"));
    expect(onChange).toHaveBeenLastCalledWith("review", { max_decisions: 5, allowed_actions: ["verify"] });
    // Mapping-required node exposes input/output mapping editors.
    expect(screen.getByLabelText("input_mapping")).toBeInTheDocument();
    expect(screen.getByLabelText("output_mapping")).toBeInTheDocument();
    // Adding an input mapping row patches node-level data (not config).
    fireEvent.click(screen.getByText("+ eşleme ekle", { selector: "fieldset[aria-label='input_mapping'] button" }));
    expect(onPatchData).toHaveBeenLastCalledWith("review", { input_mapping: [{ from: "", to: "" }] });
    // Retry editor toggles a compiler-valid default policy.
    fireEvent.click(screen.getByLabelText("retry_enabled"));
    expect(onPatchData).toHaveBeenLastCalledWith("review", {
      retry_policy: { max_attempts: 1, backoff_seconds: 0, retry_on: ["transient"], idempotent: true },
    });
  });

  it("renders generate bindings and omits a cleared optional identifier", () => {
    const onChange = vi.fn();
    const node = {
      id: "answer",
      type: "builderNode",
      position: { x: 0, y: 0 },
      data: { nodeType: "generate", config: { prompt_ref: "support_prompt" } },
    } as Node<BuilderNodeData>;
    render(<NodeConfigPanel schema={schema} node={node} disabled={false}
      onChange={onChange} onPatchData={vi.fn()} onRemove={vi.fn()} />);

    expect(screen.getByLabelText("prompt_ref")).toHaveValue("support_prompt");
    expect(screen.getByLabelText("model_profile_ref")).toHaveValue("");
    expect(screen.queryByText("Bu node için yapılandırma yok.")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("prompt_ref"), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith("answer", {});
  });
});
