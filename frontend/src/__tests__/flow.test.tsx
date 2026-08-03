import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BuilderApi } from "../api";
import { canonicalJson } from "../dsl";
import { useBuilder } from "../useBuilder";
import type { Draft, NodeSchema } from "../types";

const schema: NodeSchema = {
  organization: "b-org",
  can_write: true,
  dsl: { api_version: "agenthub/v1", kind: "Workflow" },
  limits: { max_nodes: 50, max_edges: 100 },
  node_types: [
    { type: "input", label: "Input", category: "io", fields: [], is_entry: true, singleton: true },
    { type: "format_output", label: "Format", category: "rag", fields: [] },
    { type: "end", label: "End", category: "io", is_terminal: true, fields: [] },
  ],
  tool_binding_roles: [],
  custom_nodes: [],
  projects: [],
};

function draftFixture(overrides: Partial<Draft> = {}): Draft {
  return {
    id: 1,
    organization: "b-org",
    organization_id: 1,
    project_id: null,
    scenario_id: null,
    name: "Flow",
    logical_id: "flow_a",
    body: {},
    last_published_version: 0,
    last_published_at: null,
    revision: 1,
    can_write: true,
    ...overrides,
  };
}

interface Call {
  url: string;
  method: string;
  body: unknown;
  csrf: string | undefined;
}

function mockFetch(): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, opts: RequestInit = {}) => {
      const method = (opts.method ?? "GET").toUpperCase();
      const headers = (opts.headers ?? {}) as Record<string, string>;
      const body = opts.body ? JSON.parse(opts.body as string) : undefined;
      calls.push({ url: String(url), method, body, csrf: headers["X-CSRFToken"] });
      const respond = (data: unknown) =>
        new Response(JSON.stringify(data), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      if (String(url).includes("/diagnostics/")) {
        return respond({ ok: true, errors: [], compiled_checksum: "abc123def456" });
      }
      if (String(url).includes("/publish/")) {
        return respond({
          published: true,
          artifact_type: "workflow_definition",
          logical_id: "flow_a",
          version: 1,
          checksum: "c".repeat(64),
          revision: 3,
        });
      }
      return respond({ ...draftFixture(), revision: 2 });
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("end-to-end builder flow", () => {
  it("applies a backend-validated JSON candidate to the editable graph", async () => {
    const calls = mockFetch();
    const api = new BuilderApi("/console/api/builder/");
    const { result } = renderHook(() => useBuilder(api, schema, draftFixture()));
    const candidate = {
      api_version: "agenthub/v1",
      kind: "Workflow",
      metadata: { id: "imported" },
      spec: {
        input_node: "request",
        nodes: [{ id: "request", type: "input" }, { id: "done", type: "end" }],
        edges: [{ from: "request", to: "done" }],
      },
    };

    await act(async () => {
      expect(await result.current.applyJsonCandidate(candidate)).toBe(true);
    });
    expect(result.current.workflowId).toBe("imported");
    expect(result.current.nodes.map((node) => node.id)).toEqual(["request", "done"]);
    expect(canonicalJson(result.current.body)).toBe(canonicalJson({
      ...candidate,
      spec: { ...candidate.spec, nodes: [...candidate.spec.nodes].sort((a, b) => a.id.localeCompare(b.id)) },
    }));
    expect(calls.some((call) => call.url.endsWith("/drafts/1/diagnostics/"))).toBe(true);
  });

  it("can apply an invalid transient AI repair candidate for another feedback turn", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      ok: false,
      errors: [{ code: "end_missing", message: "End node eksik." }],
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const api = new BuilderApi("/console/api/builder/");
    const transient = draftFixture({ id: 0, can_write: true });
    const { result } = renderHook(() => useBuilder(api, schema, transient));
    const candidate = {
      api_version: "agenthub/v1",
      kind: "Workflow",
      metadata: { id: "repair_turn_2" },
      spec: {
        input_node: "request",
        nodes: [{ id: "request", type: "input" }],
        edges: [],
      },
    };

    await act(async () => {
      expect(await result.current.applyJsonCandidate(candidate, true)).toBe(true);
    });
    expect(result.current.workflowId).toBe("repair_turn_2");
    expect(result.current.diagnostics?.ok).toBe(false);
    expect(result.current.status).toContain("düzeltmeye devam edin");
  });

  it("builds a graph, validates, saves, and publishes through the backend API", async () => {
    document.cookie = "csrftoken=tok-123";
    const calls = mockFetch();
    const api = new BuilderApi("/console/api/builder/");
    const { result } = renderHook(() => useBuilder(api, schema, draftFixture()));

    // A freshly opened draft is not dirty.
    expect(result.current.isDirty).toBe(false);

    // Build a graph from the palette.
    act(() => result.current.addNode("input"));
    act(() => result.current.addNode("format_output"));
    act(() => result.current.addNode("end"));
    act(() =>
      result.current.onConnect({
        source: "input",
        target: "format_output",
        sourceHandle: null,
        targetHandle: null,
      }),
    );
    act(() =>
      result.current.onConnect({
        source: "format_output",
        target: "end",
        sourceHandle: null,
        targetHandle: null,
      }),
    );

    expect(result.current.isDirty).toBe(true);
    expect(result.current.body.spec.input_node).toBe("input");
    expect(result.current.body.spec.nodes.map((n) => n.id)).toEqual([
      "end",
      "format_output",
      "input",
    ]);

    // Validate against the backend compiler.
    await act(async () => {
      await result.current.runDiagnostics();
    });
    expect(result.current.diagnostics?.ok).toBe(true);

    // Save the draft.
    await act(async () => {
      await result.current.save();
    });
    expect(result.current.isDirty).toBe(false);

    // Publish through the shared path.
    await act(async () => {
      await result.current.publish();
    });
    expect(result.current.status).toContain("Yayımlandı");

    // The DSL sent to diagnostics carried the full graph, and writes carried CSRF.
    const diag = calls.find((c) => c.url.includes("/diagnostics/"));
    expect((diag?.body as { body: { spec: { nodes: unknown[] } } }).body.spec.nodes).toHaveLength(3);
    expect(diag?.csrf).toBe("tok-123");
    const save = calls.find((c) => c.url.endsWith("/drafts/1/") && c.method === "PUT");
    expect((save?.body as { revision: number }).revision).toBe(1);
    const publish = calls.find((c) => c.url.includes("/publish/"));
    expect((publish?.body as { revision: number }).revision).toBe(2);
    expect(calls.some((c) => c.url.includes("/publish/") && c.method === "POST")).toBe(true);
  });

  it("read-only mode blocks graph edits and saves", async () => {
    mockFetch();
    const api = new BuilderApi("/console/api/builder/");
    const { result } = renderHook(() =>
      useBuilder(api, schema, draftFixture({ can_write: false })),
    );

    expect(result.current.readOnly).toBe(true);
    act(() => result.current.addNode("input"));
    expect(result.current.nodes).toHaveLength(0);

    await act(async () => {
      await result.current.save();
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("publishes a dirty draft with the revision returned by its save", async () => {
    const calls = mockFetch();
    const api = new BuilderApi("/console/api/builder/");
    const { result } = renderHook(() => useBuilder(api, schema, draftFixture()));
    act(() => result.current.addNode("input"));

    await act(async () => {
      await result.current.publish();
    });

    const save = calls.find((call) => call.url.endsWith("/drafts/1/") && call.method === "PUT");
    const publish = calls.find((call) => call.url.includes("/publish/"));
    expect((save?.body as { revision: number }).revision).toBe(1);
    expect((publish?.body as { revision: number }).revision).toBe(2);
  });

  it("saves prompt/model authoring through the node-bound endpoint and adopts hidden refs", async () => {
    const profileId = "11111111-1111-4111-8111-111111111111";
    const sourceBody = {
      api_version: "agenthub/v1", kind: "Workflow", metadata: { id: "flow_a" },
      spec: {
        input_node: "request",
        nodes: [
          { id: "request", type: "input" },
          { id: "answer", type: "generate" },
          { id: "done", type: "end" },
        ],
        edges: [{ from: "request", to: "answer" }, { from: "answer", to: "done" }],
      },
    };
    const boundBody = structuredClone(sourceBody) as typeof sourceBody & {
      spec: { nodes: Array<{ id: string; type: string; config?: Record<string, unknown> }> };
    };
    boundBody.spec.nodes[1].config = {
      prompt_ref: "gen_abc_prompt", model_profile_ref: "gen_abc_model",
    };
    const calls: Call[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, opts: RequestInit = {}) => {
      calls.push({
        url: String(url), method: (opts.method ?? "GET").toUpperCase(),
        body: opts.body ? JSON.parse(opts.body as string) : undefined,
        csrf: undefined,
      });
      return new Response(JSON.stringify({
        draft: { ...draftFixture({ body: boundBody }), revision: 2 },
        binding: {
          node_id: "answer", prompt_text: "Yanıtla", model_profile_id: profileId, configured: true,
        },
      }), { status: 200 });
    }));
    const generateSchema: NodeSchema = {
      ...schema,
      node_types: [
        ...schema.node_types,
        { type: "generate", label: "Generate", category: "rag", fields: [] },
      ],
    };
    const api = new BuilderApi("/console/api/builder/");
    const { result } = renderHook(() => useBuilder(
      api, generateSchema, draftFixture({ body: sourceBody }),
    ));

    await act(async () => {
      await result.current.saveGenerateBinding("answer", "Yanıtla", profileId);
    });

    expect(result.current.body.spec.nodes.find((node) => node.id === "answer")?.config).toEqual({
      prompt_ref: "gen_abc_prompt", model_profile_ref: "gen_abc_model",
    });
    expect(result.current.isDirty).toBe(false);
    const call = calls[0];
    expect(call.url).toContain("/generate-nodes/answer/binding/");
    expect((call.body as { revision: number }).revision).toBe(1);
    expect((call.body as { prompt_text: string }).prompt_text).toBe("Yanıtla");
  });
});
