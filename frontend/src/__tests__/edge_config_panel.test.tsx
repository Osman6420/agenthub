import { fireEvent, render, screen } from "@testing-library/react";
import type { Edge, Node } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";

import { EdgeConfigPanel } from "../components/EdgeConfigPanel";
import type { BuilderNodeData } from "../types";

const nodes: Node<BuilderNodeData>[] = [
  { id: "a", type: "builderNode", position: { x: 0, y: 0 }, data: { nodeType: "request", config: {} } },
  { id: "b", type: "builderNode", position: { x: 0, y: 0 }, data: { nodeType: "done", config: {} } },
];

function edge(): Edge {
  return { id: "a-b", source: "a", target: "b" };
}

describe("edge config panel", () => {
  it("offers a visible remove button that calls onRemove (BUG-006)", () => {
    const onRemove = vi.fn();
    render(
      <EdgeConfigPanel
        edge={edge()}
        nodes={nodes}
        disabled={false}
        onChange={vi.fn()}
        onRemove={onRemove}
      />,
    );

    const button = screen.getByRole("button", { name: "Kenarı kaldır" });
    fireEvent.click(button);

    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("hides the remove button when the builder is read-only", () => {
    render(
      <EdgeConfigPanel
        edge={edge()}
        nodes={nodes}
        disabled={true}
        onChange={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Kenarı kaldır" })).not.toBeInTheDocument();
  });
});
