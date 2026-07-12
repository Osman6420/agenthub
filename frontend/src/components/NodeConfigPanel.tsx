import type { Node } from "@xyflow/react";
import { fieldOptions, nodeTypeSchema } from "../schema";
import type { BuilderNodeData, NodeConfig, NodeSchema } from "../types";

// Renders a config form for the selected node, generated entirely from the backend
// node-schema. Enum fields (tool binding_role, custom node_ref) are populated from the
// schema's role/ref lists — the UI never surfaces tool endpoints or secret values.
export function NodeConfigPanel({
  schema,
  node,
  disabled,
  onChange,
  onRemove,
}: {
  schema: NodeSchema;
  node: Node<BuilderNodeData> | null;
  disabled: boolean;
  onChange: (id: string, config: NodeConfig) => void;
  onRemove: () => void;
}) {
  if (!node) {
    return (
      <aside style={panelStyle}>
        <div style={{ color: "#8b95a7" }}>Select a node to configure it.</div>
      </aside>
    );
  }
  const typeSchema = nodeTypeSchema(schema, node.data.nodeType);
  const config = node.data.config ?? {};

  const setField = (name: string, value: unknown) => {
    onChange(node.id, { ...config, [name]: value });
  };

  return (
    <aside style={panelStyle}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{node.data.nodeType}</div>
      <div style={{ color: "#8b95a7", fontSize: 12, marginBottom: 12 }}>id: {node.id}</div>

      {typeSchema && typeSchema.fields.length === 0 && (
        <div style={{ color: "#8b95a7", fontSize: 13 }}>This node has no configuration.</div>
      )}

      {typeSchema?.fields.map((field) => {
        const label = `${field.name}${field.required ? " *" : ""}`;
        const value = config[field.name];
        if (field.kind === "enum") {
          const options = fieldOptions(schema, field);
          return (
            <label key={field.name} style={labelStyle}>
              {label}
              <select
                aria-label={field.name}
                disabled={disabled}
                value={typeof value === "string" ? value : ""}
                onChange={(e) => setField(field.name, e.target.value)}
                style={inputStyle}
              >
                <option value="">—</option>
                {options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
              {field.help && <span style={helpStyle}>{field.help}</span>}
            </label>
          );
        }
        if (field.kind === "object") {
          return (
            <label key={field.name} style={labelStyle}>
              {label} (JSON)
              <textarea
                aria-label={field.name}
                disabled={disabled}
                defaultValue={JSON.stringify(value ?? {}, null, 2)}
                onBlur={(e) => setField(field.name, safeJson(e.target.value))}
                rows={4}
                style={{ ...inputStyle, fontFamily: "monospace" }}
              />
            </label>
          );
        }
        return (
          <label key={field.name} style={labelStyle}>
            {label}
            <input
              aria-label={field.name}
              disabled={disabled}
              value={typeof value === "string" ? value : ""}
              onChange={(e) => setField(field.name, e.target.value)}
              style={inputStyle}
            />
            {field.help && <span style={helpStyle}>{field.help}</span>}
          </label>
        );
      })}

      {!disabled && (
        <button type="button" onClick={onRemove} style={removeStyle}>
          Remove node
        </button>
      )}
    </aside>
  );
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

const panelStyle: React.CSSProperties = {
  width: 280,
  borderLeft: "1px solid #262b36",
  padding: 14,
  overflowY: "auto",
};
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
