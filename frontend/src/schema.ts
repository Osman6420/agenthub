// Helpers that derive palette entries and node-config form fields from the backend
// node-schema. The schema is authoritative and remote; this module only reads it.

import type { NodeConfig, NodeFieldSchema, NodeSchema, NodeTypeSchema } from "./types";

export function nodeTypeSchema(schema: NodeSchema, type: string): NodeTypeSchema | undefined {
  return schema.node_types.find((n) => n.type === type);
}

/** Resolve the selectable options for an enum/list field from the schema or inline list. */
export function fieldOptions(schema: NodeSchema, field: NodeFieldSchema): string[] {
  if (field.options_ref === "tool_binding_roles") {
    return schema.tool_binding_roles.map((r) => r.role);
  }
  if (field.options_ref === "custom_nodes") {
    return schema.custom_nodes.map((c) => c.node_ref);
  }
  if (Array.isArray(field.options)) return field.options;
  return [];
}

/** An empty config skeleton for a freshly added node (values filled in the config panel). */
export function defaultConfig(nodeType: NodeTypeSchema | undefined): NodeConfig {
  const config: NodeConfig = {};
  if (!nodeType) return config;
  for (const field of nodeType.fields) {
    if (!field.required) continue;
    if (field.kind === "object") config[field.name] = {};
    else if (field.kind === "list" || field.kind === "mapping") config[field.name] = [];
    else if (field.kind === "boolean") config[field.name] = false;
    else config[field.name] = "";
  }
  return config;
}

/** Suggest a unique node id like "tool", "tool-2" given the ids already in use. */
export function suggestNodeId(type: string, existing: Set<string>): string {
  if (!existing.has(type)) return type;
  let n = 2;
  while (existing.has(`${type}-${n}`)) n += 1;
  return `${type}-${n}`;
}
