import { Background, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import type { Connection, IsValidConnection } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Palette } from "./components/Palette";
import { NodeConfigPanel } from "./components/NodeConfigPanel";
import { Toolbar } from "./components/Toolbar";
import { WorkflowNode } from "./components/WorkflowNode";
import { ApiError, type BuilderApi } from "./api";
import { useBuilder } from "./useBuilder";
import type { DiagnosticsResult, Draft, NodeSchema } from "./types";

import "@xyflow/react/dist/style.css";

const nodeTypes = { builderNode: WorkflowNode };

export function Editor({
  api,
  schema,
  draft,
  onSaveTransient,
  initialDiagnostics,
}: {
  api: BuilderApi;
  schema: NodeSchema;
  draft: Draft;
  onSaveTransient?: (body: Record<string, unknown>, name: string) => Promise<void>;
  initialDiagnostics?: DiagnosticsResult;
}) {
  const builder = useBuilder(api, schema, draft, initialDiagnostics ?? null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"graph" | "json">("graph");
  const [jsonText, setJsonText] = useState(() => JSON.stringify(draft.body, null, 2));
  const [transientName, setTransientName] = useState(draft.name);
  const wrapper = useRef<HTMLDivElement>(null);
  const jsonDirty = view === "json" && jsonText !== JSON.stringify(builder.body, null, 2);

  // Unsaved-change protection against a full page unload.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (builder.isDirty || jsonDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [builder.isDirty, jsonDirty]);

  const selectedNode = useMemo(
    () => builder.nodes.find((n) => n.id === builder.selectedNodeId) ?? null,
    [builder.nodes, builder.selectedNodeId],
  );

  useEffect(() => {
    if (view === "graph") setJsonText(JSON.stringify(builder.body, null, 2));
  }, [builder.body, view]);

  const applyJson = useCallback(async () => {
    setBusy(true);
    try {
      const parsed = JSON.parse(jsonText) as unknown;
      if (await builder.applyJsonCandidate(parsed)) setView("graph");
    } catch {
      builder.setStatusError("Geçerli bir JSON nesnesi girin");
    } finally {
      setBusy(false);
    }
  }, [builder, jsonText]);

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
      {draft.id === 0 && !onSaveTransient
        ? <div style={{ padding: 10, borderBottom: "1px solid #262b36" }}>
          <strong>{draft.name}</strong> · immutable aktif workflow önizlemesi
        </div>
        : draft.id === 0 ? <div style={{ padding: 10, borderBottom: "1px solid #262b36" }}>
          <strong>AI geçici adayı</strong>
          <input aria-label="taslak görünen adı" value={transientName}
            onChange={(event) => setTransientName(event.target.value)} />
          <button type="button" disabled={busy} onClick={() => void runAction("validate")}>Doğrula</button>
          <button type="button" disabled={busy || !transientName.trim()}
            onClick={() => {
              setBusy(true);
              void onSaveTransient?.(
                builder.body as unknown as Record<string, unknown>, transientName,
              ).catch((error: unknown) => {
                builder.setStatusError(error instanceof ApiError ? error.code : String(error));
              }).finally(() => setBusy(false));
            }}>
            Kaydet
          </button>
          <span style={{ marginLeft: 8 }}>Henüz DB kaydı değildir; yayımlama ayrı adımdır.</span>
          {builder.diagnostics && !builder.diagnostics.ok && <div role="alert">
            {builder.diagnostics.errors.map((error) => <div key={error.code}>
              {error.code}: {error.message}
            </div>)}
          </div>}
        </div>
        : <Toolbar builder={builder} draftName={draft.name} busy={busy || jsonDirty} onAction={runAction} />}
      <div style={{ display: "flex", gap: 8, padding: "8px 0" }}>
        <button type="button" aria-pressed={view === "graph"} onClick={() => {
          if (view === "json" && !builder.readOnly && jsonDirty) void applyJson();
          else setView("graph");
        }}>Graph</button>
        <button type="button" aria-pressed={view === "json"} onClick={() => {
          setJsonText(JSON.stringify(builder.body, null, 2)); setView("json");
        }}>JSON</button>
      </div>
      {view === "json" ? <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
        {jsonDirty && <div role="status">JSON değişikliklerini kaydetmeden önce doğrulayıp grafe uygulayın.</div>}
        <textarea aria-label="workflow JSON" value={jsonText} disabled={builder.readOnly}
          onChange={(event) => setJsonText(event.target.value)}
          style={{ flex: 1, minHeight: 420, fontFamily: "monospace", padding: 12 }} />
        {!builder.readOnly && <button type="button" disabled={busy} onClick={() => void applyJson()}>
          JSON'ı doğrula ve grafe uygula
        </button>}
      </div> :
      <div className="ah-builder-editor-body">
        <Palette schema={schema} disabled={builder.readOnly} onAdd={builder.addNode} />
        <div
          ref={wrapper}
          className="ah-builder-canvas"
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
      </div>}
    </div>
  );
}
