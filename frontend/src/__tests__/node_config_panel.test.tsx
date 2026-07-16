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

describe("node config panel", () => {
  it("renders generate bindings and omits a cleared optional identifier", () => {
    const onChange = vi.fn();
    const node = {
      id: "answer",
      type: "builderNode",
      position: { x: 0, y: 0 },
      data: { nodeType: "generate", config: { prompt_ref: "support_prompt" } },
    } as Node<BuilderNodeData>;
    render(<NodeConfigPanel schema={schema} node={node} disabled={false}
      onChange={onChange} onRemove={vi.fn()} />);

    expect(screen.getByLabelText("prompt_ref")).toHaveValue("support_prompt");
    expect(screen.getByLabelText("model_profile_ref")).toHaveValue("");
    expect(screen.queryByText("Bu node için yapılandırma yok.")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("prompt_ref"), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith("answer", {});
  });
});
