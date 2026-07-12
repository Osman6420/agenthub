import type { Edge, Node } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { canonicalJson, dslToGraph, graphToDsl } from "../dsl";
import type { BuilderNodeData } from "../types";

function node(id: string, nodeType: string, config: Record<string, unknown> = {}): Node<BuilderNodeData> {
  return { id, type: "builderNode", position: { x: 0, y: 0 }, data: { nodeType, config } };
}

describe("canonicalJson", () => {
  it("is stable regardless of key order", () => {
    expect(canonicalJson({ b: 1, a: { d: 2, c: 3 } })).toBe(canonicalJson({ a: { c: 3, d: 2 }, b: 1 }));
  });
});

describe("graphToDsl", () => {
  it("sorts nodes by id and omits empty configs", () => {
    const dsl = graphToDsl({
      workflowId: "wf.v1",
      inputNodeId: "request",
      nodes: [
        node("request", "input"),
        node("format", "format_output", { template_ref: "ok" }),
        node("done", "end"),
      ],
      edges: [
        { id: "e1", source: "format", target: "done" } as Edge,
        { id: "e2", source: "request", target: "format" } as Edge,
      ],
    });
    expect(dsl.spec.nodes.map((n) => n.id)).toEqual(["done", "format", "request"]);
    expect(dsl.spec.nodes.find((n) => n.id === "request")?.config).toBeUndefined();
    expect(dsl.spec.nodes.find((n) => n.id === "format")?.config).toEqual({ template_ref: "ok" });
    expect(dsl.spec.edges).toEqual([
      { from: "format", to: "done" },
      { from: "request", to: "format" },
    ]);
  });

  it("is deterministic: identical graphs yield byte-identical canonical output", () => {
    const build = (order: 1 | 2) =>
      graphToDsl({
        workflowId: "wf.v1",
        inputNodeId: "request",
        nodes:
          order === 1
            ? [node("request", "input"), node("done", "end")]
            : [node("done", "end"), node("request", "input")],
        edges: [{ id: "e", source: "request", target: "done" } as Edge],
      });
    expect(canonicalJson(build(1))).toBe(canonicalJson(build(2)));
  });

  it("carries the typed 'when' flag on condition edges only", () => {
    const dsl = graphToDsl({
      workflowId: "wf.v1",
      inputNodeId: "request",
      nodes: [node("request", "input"), node("branch", "condition"), node("done", "end")],
      edges: [
        { id: "e1", source: "branch", target: "done", data: { when: true } } as Edge,
        { id: "e2", source: "request", target: "branch" } as Edge,
      ],
    });
    expect(dsl.spec.edges).toEqual([
      { from: "branch", to: "done", when: true },
      { from: "request", to: "branch" },
    ]);
  });
});

describe("dslToGraph round-trip", () => {
  it("preserves the canonical body through parse and re-serialize", () => {
    const body = graphToDsl({
      workflowId: "wf.v1",
      inputNodeId: "request",
      nodes: [
        node("request", "input"),
        node("format", "format_output", { template_ref: "ok" }),
        node("done", "end"),
      ],
      edges: [
        { id: "e1", source: "request", target: "format" } as Edge,
        { id: "e2", source: "format", target: "done" } as Edge,
      ],
    });
    const parsed = dslToGraph(body);
    const reserialized = graphToDsl({
      workflowId: parsed.workflowId,
      inputNodeId: parsed.inputNodeId,
      nodes: parsed.nodes,
      edges: parsed.edges,
    });
    expect(canonicalJson(reserialized)).toBe(canonicalJson(body));
  });

  it("returns an empty graph for a malformed body instead of throwing", () => {
    expect(dslToGraph(null).nodes).toEqual([]);
    expect(dslToGraph({ spec: 123 }).nodes).toEqual([]);
  });
});
