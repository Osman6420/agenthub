import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";

const draft = {
  id: 9,
  organization: "org-b",
  organization_id: 2,
  project_id: 4,
  name: "Deep linked graph",
  logical_id: "graph",
  body: {
    api_version: "agenthub/v1",
    kind: "Workflow",
    metadata: { id: "graph" },
    spec: {
      input_node: "request",
      nodes: [
        { id: "request", type: "input" },
        { id: "done", type: "end" },
      ],
      edges: [{ from: "request", to: "done" }],
    },
  },
  last_published_version: 1,
  last_published_at: null,
  can_write: false,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("builder deep link", () => {
  it("selects the server-provided organization and opens its scoped draft", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(String(url));
        const value = String(url);
        let payload: unknown;
        if (value.includes("node-schema")) {
          payload = {
            organization: "org-b",
            can_write: false,
            dsl: { api_version: "agenthub/v1", kind: "Workflow" },
            limits: { max_nodes: 50, max_edges: 100 },
            node_types: [
              { type: "input", label: "Input", category: "io", fields: [], is_entry: true },
              { type: "end", label: "End", category: "io", fields: [], is_terminal: true },
            ],
            tool_binding_roles: [],
            custom_nodes: [],
            projects: [{ id: 4, slug: "project", name: "Project" }],
          };
        } else if (value.endsWith("/drafts/")) {
          payload = { drafts: [draft] };
        } else if (value.endsWith("/drafts/9/")) {
          payload = draft;
        } else {
          payload = {};
        }
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    render(
      <App
        apiBase="/console/api/builder/"
        orgs={[
          { slug: "org-a", name: "A", can_write: true },
          { slug: "org-b", name: "B", can_write: false },
        ]}
        initial={{ organization: "org-b", draft_id: 9 }}
      />,
    );

    await waitFor(() => expect(calls).toContain("/console/api/builder/drafts/9/"));
    expect(calls.some((url) => url.includes("organization=org-b"))).toBe(true);
    expect(calls.some((url) => url.includes("organization=org-a"))).toBe(false);
  });
});
