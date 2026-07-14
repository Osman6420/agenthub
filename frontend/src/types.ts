// Shared types for the workflow builder. These mirror the backend node-schema and DSL
// shapes but hold no authoritative logic — validation and publishing live on the server.

export interface OrgOption {
  slug: string;
  name: string;
  can_write: boolean;
}

export interface BuilderInitial {
  organization?: string;
  draft_id?: number;
}

export interface NodeFieldSchema {
  name: string;
  kind: "expression" | "identifier" | "enum" | "object";
  required?: boolean;
  help?: string;
  options_ref?: "tool_binding_roles" | "custom_nodes";
}

export interface NodeTypeSchema {
  type: string;
  label: string;
  category: string;
  fields: NodeFieldSchema[];
  singleton?: boolean;
  is_entry?: boolean;
  is_terminal?: boolean;
  has_conditional_edges?: boolean;
}

export interface ToolBindingRole {
  role: string;
  approval_required: boolean;
}

export interface NodeSchema {
  organization: string;
  can_write: boolean;
  dsl: { api_version: string; kind: string };
  limits: { max_nodes: number; max_edges: number };
  node_types: NodeTypeSchema[];
  tool_binding_roles: ToolBindingRole[];
  custom_nodes: { node_ref: string }[];
  projects: { id: number; slug: string; name: string }[];
}

export type NodeConfig = Record<string, unknown>;

export interface DslNode {
  id: string;
  type: string;
  config?: NodeConfig;
}

export interface DslEdge {
  from: string;
  to: string;
  when?: boolean;
}

export interface WorkflowDsl {
  api_version: string;
  kind: string;
  metadata: { id: string };
  spec: {
    input_node: string;
    nodes: DslNode[];
    edges: DslEdge[];
  };
}

export interface Draft {
  id: number;
  organization: string;
  organization_id: number;
  project_id: number | null;
  name: string;
  logical_id: string;
  body: Record<string, unknown>;
  last_published_version: number;
  last_published_at: string | null;
  can_write: boolean;
}

export interface DiagnosticsResult {
  ok: boolean;
  errors: { code: string; message: string }[];
  compiled_checksum?: string;
}

export interface AiCandidateResult {
  candidate: Record<string, unknown>;
  diagnostics: DiagnosticsResult;
}

// Node data carried inside a React Flow node.
export interface BuilderNodeData {
  nodeType: string;
  config: NodeConfig;
  hasError?: boolean;
  [key: string]: unknown;
}
