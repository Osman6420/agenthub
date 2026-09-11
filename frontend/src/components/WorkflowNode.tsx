import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import type { BuilderNodeData } from "../types";

// A single workflow node on the canvas. Entry (input) nodes get only a source handle,
// terminal (end) nodes only a target handle; everything else gets both. A backend
// diagnostic naming this node turns its border red.
export function WorkflowNode({ id, data, selected }: NodeProps) {
  const nodeData = data as BuilderNodeData;
  const type = nodeData.nodeType;
  const isEntry = type === "input";
  const isTerminal = type === "end";
  const border = nodeData.hasError ? "#f87171" : selected ? "#3b82f6" : "#3a4353";
  return (
    <div
      data-testid={`node-${id}`}
      style={{
        border: `2px solid ${border}`,
        borderRadius: 8,
        background: "#1b2029",
        color: "#e6e6e6",
        padding: "8px 12px",
        minWidth: 120,
        fontSize: 13,
      }}
    >
      {!isEntry && <Handle type="target" position={Position.Left} />}
      <div style={{ fontWeight: 600 }}>{type}</div>
      <div style={{ color: "#8b95a7", fontSize: 11 }}>{id}</div>
      {!isTerminal && <Handle type="source" position={Position.Right} />}
    </div>
  );
}
