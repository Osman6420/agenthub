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
  scenario_public_id?: string;
  scenario_name?: string;
  project_name?: string;
  can_author_scenario?: boolean;
  can_compile_release?: boolean;
  artifact_options_url?: string;
  ai_authoring?: {
    available: boolean;
    message: string;
  };
  active_workflow?: {
    logical_id: string;
    name: string;
    version: number;
    checksum: string;
    body: Record<string, unknown>;
  };
}

export interface ManifestTypeOption {
  value: string;
  label: string;
  description: string;
}

export interface ManifestLogicalOption {
  value: string;
  label: string;
  description: string;
  latest_version: number;
}

export interface ManifestVersionOption {
  id: number;
  version: number;
  description: string;
  checksum: string;
  status: string;
  pinned_release_count: number;
}

export interface ArtifactVersionPreview {
  id: number;
  artifact_type: string;
  logical_id: string;
  logical_description: string;
  version: number;
  version_description: string;
  checksum: string;
  body: Record<string, unknown> | null;
  body_too_large: boolean;
  can_create_new_version: boolean;
}

export interface ManifestOptionsResult {
  level: "artifact_type" | "logical_artifact" | "exact_version" | "preset";
  artifact_type?: string;
  logical_id?: string;
  logical_description?: string;
  roles?: string[];
  options: ManifestTypeOption[] | ManifestLogicalOption[] | ManifestVersionOption[] |
    ManifestPresetOption[];
  limited?: boolean;
  missing_roles?: string[];
  recommendation_only?: boolean;
}

export interface ManifestSelectionPayload {
  artifact_version_id: number;
  role: string;
}

export interface ManifestPresetOption extends ManifestSelectionPayload {
  artifactType: string;
  logicalId: string;
  version: number;
  checksum: string;
  description: string;
}

export interface ReleaseDiagnostic {
  code: string;
  message: string;
  role?: string;
  artifact_type?: string;
  node_id?: string;
  json_pointer?: string;
}

export interface ManifestPreflightResult {
  ok: boolean;
  diagnostics: ReleaseDiagnostic[];
  artifact_manifest_sha256?: string;
}

export interface ManifestCompileResult extends ManifestPreflightResult {
  release?: {
    id: number;
    status: string;
    artifact_manifest_sha256: string;
  };
}

export interface ManifestRequirement {
  role: string;
  artifact_type: string;
  node_ids: string[];
}

export interface ManifestRequirementsResult extends ManifestPreflightResult {
  workflow?: {
    artifact_version_id: number;
    logical_id: string;
    version: number;
    checksum: string;
  };
  requirements?: ManifestRequirement[];
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
  agent_loop?: boolean;
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
  gates?: { composition_enabled: boolean; agent_loop_enabled?: boolean };
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
  logical_description?: string;
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
  repair?: {
    before_diagnostic_codes: string[];
    after_diagnostic_codes: string[];
  };
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
  artifact_type: "input_contract" | "output_contract" | "prompt_template";
  organization: string;
  organization_id: number;
  project_id: number | null;
  scenario_id: number | null;
  name: string;
  logical_id: string;
  logical_description: string;
  body: Record<string, unknown>;
  last_published_version: number;
  last_published_at: string | null;
  updated_at: string;
  revision: number;
  can_write: boolean;
}

export interface ArtifactPublishResult {
  published: boolean;
  artifact_version_id: number;
  artifact_type: string;
  logical_id: string;
  logical_description: string;
  version: number;
  version_description: string;
  checksum: string;
  revision: number;
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
