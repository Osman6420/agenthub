import { describe, expect, it } from "vitest";

import { defaultConfig, fieldOptions, nodeTypeSchema, suggestNodeId } from "../schema";
import type { NodeSchema } from "../types";

const schema: NodeSchema = {
  organization: "b-org",
  can_write: true,
  dsl: { api_version: "agenthub/v1", kind: "Workflow" },
  limits: { max_nodes: 50, max_edges: 100 },
  node_types: [
    { type: "input", label: "Input", category: "io", fields: [], is_entry: true, singleton: true },
    {
      type: "tool",
      label: "Tool",
      category: "tool",
      fields: [
        { name: "binding_role", kind: "enum", required: true, options_ref: "tool_binding_roles" },
        { name: "input_key", kind: "identifier", required: true },
        { name: "output_key", kind: "identifier", required: true },
      ],
    },
    {
      type: "custom",
      label: "Custom",
      category: "custom",
      fields: [
        { name: "node_ref", kind: "enum", required: true, options_ref: "custom_nodes" },
        { name: "fields", kind: "object" },
      ],
    },
  ],
  tool_binding_roles: [{ role: "search_web", approval_required: true }],
  custom_nodes: [{ node_ref: "summarize" }],
};

describe("schema helpers", () => {
  it("resolves enum options from the shared lists", () => {
    const toolField = schema.node_types[1].fields[0];
    const customField = schema.node_types[2].fields[0];
    expect(fieldOptions(schema, toolField)).toEqual(["search_web"]);
    expect(fieldOptions(schema, customField)).toEqual(["summarize"]);
  });

  it("builds an empty default config from the field list", () => {
    expect(defaultConfig(nodeTypeSchema(schema, "tool"))).toEqual({
      binding_role: "",
      input_key: "",
      output_key: "",
    });
    expect(defaultConfig(nodeTypeSchema(schema, "custom"))).toEqual({ node_ref: "", fields: {} });
    expect(defaultConfig(nodeTypeSchema(schema, "input"))).toEqual({});
  });

  it("suggests unique node ids", () => {
    expect(suggestNodeId("tool", new Set())).toBe("tool");
    expect(suggestNodeId("tool", new Set(["tool"]))).toBe("tool-2");
    expect(suggestNodeId("tool", new Set(["tool", "tool-2"]))).toBe("tool-3");
  });
});
