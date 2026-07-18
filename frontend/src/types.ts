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
  project_id?: number;
  scenario_id?: number;
  scenario_name?: string;
  project_name?: string;
  active_workflow?: {
    logical_id: string;
    name: string;
    version: number;
    checksum: string;
    body: Record<string, unknown>;
  };
}

export interface NodeFieldSchema {
  name: string;
  kind:
    | "expression"
    | "identifier"
    | "text"
    | "enum"
    | "object"
    | "integer"
    | "boolean"
    | "list"
    | "pointer"
    | "mapping";
  required?: boolean;
  help?: string;
  options_ref?: "tool_binding_roles" | "custom_nodes";
  options?: string[];
  min?: number;
  max?: number;
  max_items?: number;
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
  supports_mapping?: boolean;
  mapping_required?: boolean;
  supports_retry?: boolean;
  supports_compensation?: boolean;
  branch_owner?: boolean;
  composition?: boolean;
}

export interface ToolBindingRole {
  role: string;
  approval_required: boolean;
}

export interface RetryPolicySchema {
  max_attempts: { min: number; max: number };
  backoff_seconds: { min: number; max: number };
  retry_on: string[];
  idempotent_required: boolean;
}

export interface NodeSchema {
  organization: string;
  can_write: boolean;
  dsl: { api_version: string; kind: string };
  limits: { max_nodes: number; max_edges: number; max_parallel_branches?: number };
  node_types: NodeTypeSchema[];
  retry_policy?: RetryPolicySchema;
  gates?: { composition_enabled: boolean };
  tool_binding_roles: ToolBindingRole[];
  custom_nodes: { node_ref: string }[];
  projects: { id: number; slug: string; name: string }[];
}

export type NodeConfig = Record<string, unknown>;

export interface MappingEntry {
  from: string;
  to: string;
}

export interface RetryPolicy {
  max_attempts: number;
  backoff_seconds: number;
  retry_on: string[];
  idempotent: boolean;
}

export interface DslNode {
  id: string;
  type: string;
  config?: NodeConfig;
  input_mapping?: MappingEntry[];
  output_mapping?: MappingEntry[];
  retry_policy?: RetryPolicy;
  compensation?: string;
}

export interface DslEdge {
  from: string;
  to: string;
  when?: boolean;
  branch?: string;
  on_error?: string;
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
  scenario_id: number | null;
  name: string;
  logical_id: string;
  body: Record<string, unknown>;
  last_published_version: number;
  last_published_at: string | null;
  revision: number;
  can_write: boolean;
}

export interface DiagnosticsResult {
  ok: boolean;
  errors: { code: string; message: string }[];
  compiled_checksum?: string;
}

export interface AiCandidateResult {
  status: "workflow_candidate";
  artifact_type: AiCandidateType;
  candidate: Record<string, unknown>;
  diagnostics: DiagnosticsResult;
  prompt_contract: { id: string; revision: number; checksum: string };
  authoring_context: { contract: string; checksum: string };
}

export interface CapabilityMissingResult {
  status: "capability_missing";
  required_capability: string;
  suggestion: Record<string, unknown>;
  authoring_context: { contract: string; checksum: string };
}

export type AiCandidateType = "workflow_definition" | "input_contract" | "output_contract";

export interface ArtifactDraft {
  id: number;
  draft_kind: "artifact";
  artifact_type: "input_contract" | "output_contract";
  organization: string;
  organization_id: number;
  project_id: number | null;
  name: string;
  logical_id: string;
  body: Record<string, unknown>;
  updated_at: string;
  revision: number;
  can_write: boolean;
}

export type AcceptedCandidateDraft = Draft | ArtifactDraft;

// Node data carried inside a React Flow node. Beyond ``config``, mapping-eligible nodes
// carry input/output mappings, retry-eligible nodes carry a retry_policy, and tool nodes
// may carry a compensation reference — all DSL-shaped and non-authoritative.
export interface BuilderNodeData {
  nodeType: string;
  config: NodeConfig;
  input_mapping?: MappingEntry[];
  output_mapping?: MappingEntry[];
  retry_policy?: RetryPolicy;
  compensation?: string;
  hasError?: boolean;
  [key: string]: unknown;
}
