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
export function graphToDsl(params: GraphToDslParams): WorkflowDsl {
  const dslNodes: DslNode[] = params.nodes
    .map((node) => {
      const data = node.data;
      const base: DslNode = { id: node.id, type: data.nodeType };
      if (!isEmptyConfig(data.config)) {
        base.config = data.config;
      }
      return base;
    })
    .sort((a, b) => a.id.localeCompare(b.id));

  const dslEdges: DslEdge[] = params.edges
    .map((edge) => {
      const out: DslEdge = { from: edge.source, to: edge.target };
      const when = (edge.data as { when?: boolean } | undefined)?.when;
      if (typeof when === "boolean") {
        out.when = when;
      }
      return out;
    })
    .sort(
      (a, b) =>
        a.from.localeCompare(b.from) ||
        String(a.when).localeCompare(String(b.when)) ||
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

  const nodes: Node<BuilderNodeData>[] = spec.nodes.map((n, index) => ({
    id: n.id,
    type: "builderNode",
    position: layoutPosition(index),
    data: { nodeType: n.type, config: (n.config as Record<string, unknown>) ?? {} },
  }));

  const edges: Edge[] = (spec.edges ?? []).map((e, index) => ({
    id: `e-${e.from}-${e.to}-${index}`,
    source: e.from,
    target: e.to,
    data: typeof e.when === "boolean" ? { when: e.when } : {},
    label: typeof e.when === "boolean" ? String(e.when) : undefined,
  }));

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
  return { x: 60 + Math.floor(index / perColumn) * 260, y: 40 + (index % perColumn) * 120 };
}
