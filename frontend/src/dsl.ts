// Deterministic serialization between the React Flow graph and the workflow DSL.
//
// The backend is the source of truth for validation; this module only produces a stable,
// canonical DSL body so that (a) the same graph always yields byte-identical output and
// (b) unsaved-change detection is reliable. Canonicalization mirrors the backend's
// canonical_json (recursively sorted keys), so the frontend's notion of "changed" matches
// the artifact checksum boundary.

import type { Edge, Node } from "@xyflow/react";
import type { BuilderNodeData, DslEdge, DslNode, WorkflowDsl } from "./types";

export const API_VERSION = "agenthub/v1";
export const KIND = "Workflow";

/** Recursively sort object keys to produce a stable, comparable JSON string. */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(sortValue(value));
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortValue);
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      out[key] = sortValue((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}

function isEmptyConfig(config: unknown): boolean {
  return !config || (typeof config === "object" && Object.keys(config).length === 0);
}

export interface GraphToDslParams {
  workflowId: string;
  inputNodeId: string;
  nodes: Node<BuilderNodeData>[];
  edges: Edge[];
}

/**
 * Build a deterministic DSL body from the current graph. Nodes are sorted by id and edges
 * by (from, when, to); empty configs are omitted (the compiler forbids config on
 * input/validate_contract/end nodes). Node positions are intentionally excluded — layout
 * is not part of the versioned DSL.
 */
function isEmptyMapping(entries: unknown): boolean {
  return !Array.isArray(entries) || entries.length === 0;
}

export function graphToDsl(params: GraphToDslParams): WorkflowDsl {
  const dslNodes: DslNode[] = params.nodes
    .map((node) => {
      const data = node.data;
      const base: DslNode = { id: node.id, type: data.nodeType };
      if (!isEmptyConfig(data.config)) {
        base.config = data.config;
      }
      // Node-level DSL siblings (mappings/retry/compensation) are emitted only when set,
      // so an untouched node stays byte-identical to the pre-P2.6.11 serialization.
      if (!isEmptyMapping(data.input_mapping)) base.input_mapping = data.input_mapping;
      if (!isEmptyMapping(data.output_mapping)) base.output_mapping = data.output_mapping;
      if (data.retry_policy) base.retry_policy = data.retry_policy;
      if (typeof data.compensation === "string" && data.compensation !== "") {
        base.compensation = data.compensation;
      }
      return base;
    })
    .sort((a, b) => a.id.localeCompare(b.id));

  const dslEdges: DslEdge[] = params.edges
    .map((edge) => {
      const out: DslEdge = { from: edge.source, to: edge.target };
      const data = edge.data as { when?: boolean; branch?: string; on_error?: string } | undefined;
      // The compiler treats when/branch/on_error as mutually exclusive selectors; emit at
      // most one, matching that contract.
      if (typeof data?.when === "boolean") out.when = data.when;
      else if (typeof data?.branch === "string" && data.branch !== "") out.branch = data.branch;
      else if (typeof data?.on_error === "string" && data.on_error !== "") {
        out.on_error = data.on_error;
      }
      return out;
    })
    .sort(
      (a, b) =>
        a.from.localeCompare(b.from) ||
        String(a.when).localeCompare(String(b.when)) ||
        String(a.branch).localeCompare(String(b.branch)) ||
        String(a.on_error).localeCompare(String(b.on_error)) ||
        a.to.localeCompare(b.to),
    );

  return {
    api_version: API_VERSION,
    kind: KIND,
    metadata: { id: params.workflowId },
    spec: {
      input_node: params.inputNodeId,
      nodes: dslNodes,
      edges: dslEdges,
    },
  };
}

export interface ParsedGraph {
  workflowId: string;
  inputNodeId: string;
  nodes: Node<BuilderNodeData>[];
  edges: Edge[];
}

/**
 * Parse a stored DSL body into graph state for editing. Unknown/partial bodies yield an
 * empty graph rather than throwing — the editor must stay usable on invalid drafts.
 * Layout is regenerated deterministically since positions are not persisted.
 */
export function dslToGraph(body: unknown): ParsedGraph {
  const empty: ParsedGraph = { workflowId: "", inputNodeId: "", nodes: [], edges: [] };
  if (!body || typeof body !== "object") return empty;
  const dsl = body as Partial<WorkflowDsl>;
  const spec = dsl.spec;
  if (!spec || !Array.isArray(spec.nodes)) return empty;

  const nodes: Node<BuilderNodeData>[] = spec.nodes.map((n, index) => {
    const data: BuilderNodeData = {
      nodeType: n.type,
      config: (n.config as Record<string, unknown>) ?? {},
    };
    if (Array.isArray(n.input_mapping)) data.input_mapping = n.input_mapping;
    if (Array.isArray(n.output_mapping)) data.output_mapping = n.output_mapping;
    if (n.retry_policy) data.retry_policy = n.retry_policy;
    if (typeof n.compensation === "string") data.compensation = n.compensation;
    return { id: n.id, type: "builderNode", position: layoutPosition(index), data };
  });

  const edges: Edge[] = (spec.edges ?? []).map((e, index) => {
    const data: { when?: boolean; branch?: string; on_error?: string } = {};
    let label: string | undefined;
    if (typeof e.when === "boolean") {
      data.when = e.when;
      label = String(e.when);
    } else if (typeof e.branch === "string") {
      data.branch = e.branch;
      label = `⑃ ${e.branch}`;
    } else if (typeof e.on_error === "string") {
      data.on_error = e.on_error;
      label = `⚠ ${e.on_error}`;
    }
    return { id: `e-${e.from}-${e.to}-${index}`, source: e.from, target: e.to, data, label };
  });

  return {
    workflowId: dsl.metadata?.id ?? "",
    inputNodeId: spec.input_node ?? "",
    nodes,
    edges,
  };
}

// Deterministic grid layout so a reloaded draft is laid out identically every time.
function layoutPosition(index: number): { x: number; y: number } {
  const perColumn = 4;
  const row = index % perColumn;
  // BUG-014: nodes within a column used to share one x-coordinate, but `WorkflowNode`'s
  // handles are `Position.Left`/`Position.Right` (a horizontal-flow layout) -- React Flow's
  // default bezier then had to bow far sideways to connect two vertically stacked nodes. A
  // small per-row offset keeps the staircase readable without changing handle positions or
  // the edge type, both of which would have a much wider visual effect.
  return { x: 60 + Math.floor(index / perColumn) * 260 + row * 36, y: 40 + row * 120 };
}
