// The builder controller: graph state + deterministic serialization + calls to the
// governed backend API. It holds NO authoritative validation, authorization, or publish
// logic — diagnostics and publish are backend round-trips; read-only is driven by the
// server's can_write flag. React Flow is used only for canvas rendering.

import { applyEdgeChanges, applyNodeChanges } from "@xyflow/react";
import type { Connection, Edge, EdgeChange, Node, NodeChange } from "@xyflow/react";
import { useCallback, useMemo, useState } from "react";

import type { BuilderApi } from "./api";
import { canonicalJson, dslToGraph, graphToDsl } from "./dsl";
import { defaultConfig, nodeTypeSchema, suggestNodeId } from "./schema";
import type {
  BuilderNodeData,
  DiagnosticsResult,
  Draft,
  NodeConfig,
  NodeSchema,
  WorkflowDsl,
} from "./types";

export interface BuilderController {
  nodes: Node<BuilderNodeData>[];
  edges: Edge[];
  workflowId: string;
  selectedNodeId: string | null;
  diagnostics: DiagnosticsResult | null;
  status: string;
  readOnly: boolean;
  isDirty: boolean;
  body: WorkflowDsl;
  setWorkflowId: (id: string) => void;
  setStatusError: (message: string) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection, when?: boolean) => void;
  addNode: (type: string) => void;
  selectNode: (id: string | null) => void;
  updateNodeConfig: (id: string, config: NodeConfig) => void;
  removeSelected: () => void;
  runDiagnostics: () => Promise<void>;
  save: () => Promise<void>;
  publish: () => Promise<void>;
}

export function useBuilder(api: BuilderApi, schema: NodeSchema, draft: Draft): BuilderController {
  const initial = useMemo(() => dslToGraph(draft.body), [draft.body]);
  const [nodes, setNodes] = useState<Node<BuilderNodeData>[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);
  const [workflowId, setWorkflowId] = useState<string>(initial.workflowId || draft.logical_id);
  const [inputNodeId, setInputNodeId] = useState<string>(initial.inputNodeId);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResult | null>(null);
  const [status, setStatus] = useState<string>("");

  const readOnly = !draft.can_write;

  const body = useMemo<WorkflowDsl>(
    () => graphToDsl({ workflowId, inputNodeId, nodes, edges }),
    [workflowId, inputNodeId, nodes, edges],
  );

  const [savedCanonical, setSavedCanonical] = useState<string>(() =>
    canonicalJson(
      graphToDsl({
        workflowId: initial.workflowId || draft.logical_id,
        inputNodeId: initial.inputNodeId,
        nodes: initial.nodes,
        edges: initial.edges,
      }),
    ),
  );
  const isDirty = canonicalJson(body) !== savedCanonical;

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      if (readOnly) return;
      setNodes((current) => applyNodeChanges(changes, current) as Node<BuilderNodeData>[]);
    },
    [readOnly],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      if (readOnly) return;
      setEdges((current) => applyEdgeChanges(changes, current));
    },
    [readOnly],
  );

  const onConnect = useCallback(
    (connection: Connection, when?: boolean) => {
      if (readOnly || !connection.source || !connection.target) return;
      setEdges((current) => {
        const id = `e-${connection.source}-${connection.target}-${current.length}`;
        const edge: Edge = {
          id,
          source: connection.source as string,
          target: connection.target as string,
          data: typeof when === "boolean" ? { when } : {},
          label: typeof when === "boolean" ? String(when) : undefined,
        };
        return [...current, edge];
      });
    },
    [readOnly],
  );

  const addNode = useCallback(
    (type: string) => {
      if (readOnly) return;
      const typeSchema = nodeTypeSchema(schema, type);
      setNodes((current) => {
        if (typeSchema?.singleton && current.some((n) => n.data.nodeType === type)) {
          return current;
        }
        const ids = new Set(current.map((n) => n.id));
        const id = suggestNodeId(type, ids);
        if (typeSchema?.is_entry) setInputNodeId(id);
        const node: Node<BuilderNodeData> = {
          id,
          type: "builderNode",
          position: { x: 80 + current.length * 40, y: 60 + current.length * 30 },
          data: { nodeType: type, config: defaultConfig(typeSchema) },
        };
        return [...current, node];
      });
      setStatus(`Added ${type} node`);
    },
    [readOnly, schema],
  );

  const updateNodeConfig = useCallback(
    (id: string, config: NodeConfig) => {
      if (readOnly) return;
      setNodes((current) =>
        current.map((n) => (n.id === id ? { ...n, data: { ...n.data, config } } : n)),
      );
    },
    [readOnly],
  );

  const removeSelected = useCallback(() => {
    if (readOnly || !selectedNodeId) return;
    setNodes((current) => current.filter((n) => n.id !== selectedNodeId));
    setEdges((current) =>
      current.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId),
    );
    setSelectedNodeId(null);
  }, [readOnly, selectedNodeId]);

  const applyErrorHighlights = useCallback((result: DiagnosticsResult) => {
    // Surface backend diagnostics on the graph: if a compiler message names a node id,
    // flag that node; otherwise clear highlights (the banner still shows the message).
    setNodes((current) =>
      current.map((n) => {
        const named = result.errors.some((e) => e.message.includes(`'${n.id}'`) || e.message.includes(` ${n.id} `));
        return { ...n, data: { ...n.data, hasError: !result.ok && named } };
      }),
    );
  }, []);

  const runDiagnostics = useCallback(async () => {
    const result = await api.diagnostics(draft.id, body as unknown as Record<string, unknown>);
    setDiagnostics(result);
    applyErrorHighlights(result);
    setStatus(result.ok ? "Workflow geçerli" : "Doğrulama sorun buldu");
  }, [api, applyErrorHighlights, body, draft.id]);

  const save = useCallback(async () => {
    if (readOnly) return;
    await api.updateDraft(draft.id, { body: body as unknown as Record<string, unknown> });
    setSavedCanonical(canonicalJson(body));
    setStatus("Draft kaydedildi");
  }, [api, body, draft.id, readOnly]);

  const publish = useCallback(async () => {
    if (readOnly) return;
    if (isDirty) await save();
    const result = await api.publish(draft.id);
    setStatus(`Yayımlandı: ${result.logical_id} v${result.version}`);
  }, [api, draft.id, isDirty, readOnly, save]);

  return {
    nodes,
    edges,
    workflowId,
    selectedNodeId,
    diagnostics,
    status,
    readOnly,
    isDirty,
    body,
    setWorkflowId,
    setStatusError: setStatus,
    onNodesChange,
    onEdgesChange,
    onConnect,
    addNode,
    selectNode: setSelectedNodeId,
    updateNodeConfig,
    removeSelected,
    runDiagnostics,
    save,
    publish,
  };
}
