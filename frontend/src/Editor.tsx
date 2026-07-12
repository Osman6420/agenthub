import { Background, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import type { Connection, IsValidConnection } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Palette } from "./components/Palette";
import { NodeConfigPanel } from "./components/NodeConfigPanel";
import { Toolbar } from "./components/Toolbar";
import { WorkflowNode } from "./components/WorkflowNode";
import { ApiError, type BuilderApi } from "./api";
import { useBuilder } from "./useBuilder";
import type { Draft, NodeSchema } from "./types";

import "@xyflow/react/dist/style.css";

const nodeTypes = { builderNode: WorkflowNode };

export function Editor({
  api,
  schema,
  draft,
}: {
  api: BuilderApi;
  schema: NodeSchema;
  draft: Draft;
}) {
  const builder = useBuilder(api, schema, draft);
  const [busy, setBusy] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);

  // Unsaved-change protection against a full page unload.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (builder.isDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [builder.isDirty]);

  const selectedNode = useMemo(
    () => builder.nodes.find((n) => n.id === builder.selectedNodeId) ?? null,
    [builder.nodes, builder.selectedNodeId],
  );

  // Typed edges: an outgoing edge from a condition node is auto-typed true then false.
  const onConnect = useCallback(
    (connection: Connection) => {
      const source = builder.nodes.find((n) => n.id === connection.source);
      let when: boolean | undefined;
      if (source?.data.nodeType === "condition") {
        const hasTrue = builder.edges.some(
          (e) => e.source === connection.source && (e.data as { when?: boolean })?.when === true,
        );
        when = !hasTrue;
      }
      builder.onConnect(connection, when);
    },
    [builder],
  );

  // Connection rules mirror the compiler's shape (end has no outgoing; no self loops).
  const isValidConnection: IsValidConnection = useCallback(
    (edge) => {
      if (edge.source === edge.target) return false;
      const source = builder.nodes.find((n) => n.id === edge.source);
      return source?.data.nodeType !== "end";
    },
    [builder.nodes],
  );

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/agenthub-node");
      if (type) builder.addNode(type);
    },
    [builder],
  );

  const runAction = useCallback(
    async (action: "validate" | "save" | "publish") => {
      setBusy(true);
      try {
        if (action === "validate") await builder.runDiagnostics();
        else if (action === "save") await builder.save();
        else await builder.publish();
      } catch (err) {
        const message = err instanceof ApiError ? `${err.code}: ${err.message}` : String(err);
        builder.setStatusError(message);
      } finally {
        setBusy(false);
      }
    },
    [builder],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "78vh" }}>
      <Toolbar builder={builder} draftName={draft.name} busy={busy} onAction={runAction} />
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <Palette schema={schema} disabled={builder.readOnly} onAdd={builder.addNode} />
        <div
          ref={wrapper}
          style={{ flex: 1, minWidth: 0 }}
          onDrop={onDrop}
          onDragOver={(e) => e.preventDefault()}
        >
          <ReactFlowProvider>
            <ReactFlow
              nodes={builder.nodes}
              edges={builder.edges}
              nodeTypes={nodeTypes}
              onNodesChange={builder.onNodesChange}
              onEdgesChange={builder.onEdgesChange}
              onConnect={onConnect}
              isValidConnection={isValidConnection}
              onNodeClick={(_, node) => builder.selectNode(node.id)}
              onPaneClick={() => builder.selectNode(null)}
              nodesDraggable={!builder.readOnly}
              nodesConnectable={!builder.readOnly}
              edgesReconnectable={!builder.readOnly}
              fitView
            >
              <Background />
              <Controls />
            </ReactFlow>
          </ReactFlowProvider>
        </div>
        <NodeConfigPanel
          schema={schema}
          node={selectedNode}
          disabled={builder.readOnly}
          onChange={builder.updateNodeConfig}
          onRemove={builder.removeSelected}
        />
      </div>
    </div>
  );
}
