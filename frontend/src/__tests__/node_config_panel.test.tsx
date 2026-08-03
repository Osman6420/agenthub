import { fireEvent, render, screen } from "@testing-library/react";
import type { Node } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";

import { BuilderApi } from "../api";
import { NodeConfigPanel } from "../components/NodeConfigPanel";
import type { BuilderNodeData, Draft, NodeSchema } from "../types";

const api = new BuilderApi("/console/api/builder");
const draft: Draft = {
  id: 4, organization: "org", organization_id: 1, project_id: 2, scenario_id: 3,
  name: "Flow", logical_id: "flow", body: {}, last_published_version: 0,
  last_published_at: null, revision: 1, can_write: true,
};
const commonProps = { api, draft, onSaveGenerateBinding: vi.fn() };

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
  gates: { composition_enabled: true },
  retry_policy: {
    max_attempts: { min: 1, max: 3 },
    backoff_seconds: { min: 0, max: 0 },
    retry_on: ["transient"],
    idempotent_required: true,
  },
  node_types: [
    {
      type: "subworkflow",
      label: "Alt iş akışı",
      category: "composition",
      composition: true,
      supports_mapping: true,
      mapping_required: true,
      fields: [
        { name: "workflow_role", kind: "identifier", required: true },
        { name: "max_depth", kind: "integer", required: true, min: 1, max: 3 },
      ],
    },
  ],
  tool_binding_roles: [],
  custom_nodes: [],
  projects: [],
};

describe("node config panel", () => {
  it("renders a canonical child workflow with bounded depth and mapping editors", () => {
    const onChange = vi.fn();
    const onPatchData = vi.fn();
    const node = {
      id: "review",
      type: "builderNode",
      position: { x: 0, y: 0 },
      data: { nodeType: "subworkflow", config: { workflow_role: "review", max_depth: 2 } },
    } as Node<BuilderNodeData>;
    render(
      <NodeConfigPanel
        schema={compositionSchema}
        node={node}
        disabled={false}
        onChange={onChange}
        onPatchData={onPatchData}
        onRemove={vi.fn()}
        {...commonProps}
      />,
    );

    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(screen.getByLabelText("workflow_role")).toHaveValue("review");
    expect(screen.getByLabelText("max_depth")).toHaveValue(2);
    // Mapping-required node exposes input/output mapping editors.
    expect(screen.getByLabelText("input_mapping")).toBeInTheDocument();
    expect(screen.getByLabelText("output_mapping")).toBeInTheDocument();
    // Adding an input mapping row patches node-level data (not config).
    fireEvent.click(screen.getByText("+ eşleme ekle", { selector: "fieldset[aria-label='input_mapping'] button" }));
    expect(onPatchData).toHaveBeenLastCalledWith("review", { input_mapping: [{ from: "", to: "" }] });
  });

  it("renders prompt/model authoring and hides raw manifest refs", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const body = String(url).includes("model-profile-options")
        ? { options: [], limited: false }
        : { node_id: "answer", prompt_text: "Yanıtla", model_profile_id: "", configured: false };
      return new Response(JSON.stringify(body), { status: 200 });
    }));
    const node = {
      id: "answer",
      type: "builderNode",
      position: { x: 0, y: 0 },
      data: { nodeType: "generate", config: { prompt_ref: "support_prompt" } },
    } as Node<BuilderNodeData>;
    render(<NodeConfigPanel schema={schema} node={node} disabled={false}
      onChange={vi.fn()} onPatchData={vi.fn()} onRemove={vi.fn()} {...commonProps} />);

    expect(await screen.findByLabelText("Generate prompt metni")).toHaveValue("Yanıtla");
    expect(screen.queryByLabelText("prompt_ref")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("model_profile_ref")).not.toBeInTheDocument();
    expect(screen.getByLabelText("platform model profili")).toBeInTheDocument();
    expect(screen.queryByText("Bu node için yapılandırma yok.")).not.toBeInTheDocument();
  });
});
