import type { NodeSchema } from "../types";

// The node palette. Each entry can be dragged onto the canvas (real browsers) or added
// by click (keyboard-accessible and test-friendly). Both paths funnel through the same
// addNode controller action.
export function Palette({
  schema,
  disabled,
  onAdd,
}: {
  schema: NodeSchema;
  disabled: boolean;
  onAdd: (type: string) => void;
}) {
  return (
    <aside className="ah-builder-palette">
      <div style={{ color: "#8b95a7", fontSize: 12, textTransform: "uppercase", marginBottom: 8 }}>
        Node'lar
      </div>
      {schema.node_types.map((nt) => (
        <button
          key={nt.type}
          type="button"
          disabled={disabled}
          draggable={!disabled}
          onDragStart={(e) => e.dataTransfer.setData("application/agenthub-node", nt.type)}
          onClick={() => onAdd(nt.type)}
          title={nt.category}
          style={{
            display: "block",
            width: "100%",
            textAlign: "left",
            margin: "4px 0",
            padding: "8px 10px",
            borderRadius: 7,
            border: "1px solid #333a49",
            background: disabled ? "#171a21" : "#222835",
            color: disabled ? "#5b6472" : "#cbd5e1",
            cursor: disabled ? "not-allowed" : "grab",
            fontSize: 13,
          }}
        >
          {nt.label}
        </button>
      ))}
    </aside>
  );
}
