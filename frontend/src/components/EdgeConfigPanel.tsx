import type { Edge, Node } from "@xyflow/react";
import type { EdgeSelector } from "../useBuilder";
import type { BuilderNodeData } from "../types";

// The failure classes the compiler accepts on an ``on_error`` edge (mirrors
// apps.workflows.compiler.FAILURE_CLASSES plus the ``any`` catch-all). UI hint only.
const FAILURE_CLASSES = ["any", "validation", "authorization", "permanent", "transient", "outcome_unknown"];

// Edge routing editor. when/branch/on_error are mutually exclusive selectors; which are
// offered depends on the endpoint node types, mirroring the compiler's routing rules. The
// backend remains authoritative — this only shapes the DSL.
export function EdgeConfigPanel({
  edge,
  nodes,
  disabled,
  onChange,
  onRemove,
}: {
  edge: Edge | null;
  nodes: Node<BuilderNodeData>[];
  disabled: boolean;
  onChange: (id: string, selector: EdgeSelector) => void;
  onRemove: () => void;
}) {
  if (!edge) return null;
  const source = nodes.find((n) => n.id === edge.source);
  const target = nodes.find((n) => n.id === edge.target);
  const data = edge.data as { when?: boolean; branch?: string; on_error?: string } | undefined;

  const isCondition = source?.data.nodeType === "condition";
  const branchAllowed =
    source?.data.nodeType === "parallel" ||
    source?.data.nodeType === "for_each" ||
    target?.data.nodeType === "join";

  return (
    <aside className="ah-builder-config" style={panelStyle} aria-label="edge-config">
      <div style={{ fontWeight: 600, marginBottom: 4 }}>Kenar yönlendirme</div>
      <div style={{ color: "#8b95a7", fontSize: 12, marginBottom: 12 }}>
        {edge.source} → {edge.target}
      </div>

      {isCondition && (
        <label style={labelStyle}>
          Koşul dalı (when)
          <select
            aria-label="edge_when"
            disabled={disabled}
            value={data?.when === undefined ? "" : String(data.when)}
            onChange={(e) =>
              onChange(
                edge.id,
                e.target.value === ""
                  ? { kind: "none" }
                  : { kind: "when", value: e.target.value === "true" },
              )
            }
            style={inputStyle}
          >
            <option value="">—</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </label>
      )}

      {branchAllowed && (
        <label style={labelStyle}>
          Dal etiketi (branch)
          <input
            aria-label="edge_branch"
            disabled={disabled}
            value={typeof data?.branch === "string" ? data.branch : ""}
            onChange={(e) => onChange(edge.id, { kind: "branch", value: e.target.value })}
            style={inputStyle}
          />
          <span style={helpStyle}>Paralel/for_each bölgesi veya join dalı için etiket.</span>
        </label>
      )}

      <label style={labelStyle}>
        Hata rotası (on_error)
        <select
          aria-label="edge_on_error"
          disabled={disabled}
          value={typeof data?.on_error === "string" ? data.on_error : ""}
          onChange={(e) =>
            onChange(
              edge.id,
              e.target.value === ""
                ? { kind: "none" }
                : { kind: "on_error", value: e.target.value },
            )
          }
          style={inputStyle}
        >
          <option value="">—</option>
          {FAILURE_CLASSES.map((cls) => (
            <option key={cls} value={cls}>
              {cls}
            </option>
          ))}
        </select>
        <span style={helpStyle}>Bu hata sınıfında izlenecek telafi/kurtarma rotası.</span>
      </label>

      {!disabled && (
        <button type="button" onClick={onRemove} style={removeStyle}>
          Kenarı kaldır
        </button>
      )}
    </aside>
  );
}

const panelStyle: React.CSSProperties = { padding: 14, overflowY: "auto" };
const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  color: "#a9b4c4",
  marginBottom: 12,
};
const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 4,
  padding: "6px 8px",
  borderRadius: 6,
  border: "1px solid #333a49",
  background: "#0f1115",
  color: "#e6e6e6",
};
const helpStyle: React.CSSProperties = { display: "block", color: "#6b7280", marginTop: 3 };
const removeStyle: React.CSSProperties = {
  marginTop: 8,
  padding: "6px 10px",
  borderRadius: 6,
  border: "1px solid #7f1d1d",
  background: "#2a1417",
  color: "#fca5a5",
  cursor: "pointer",
};
