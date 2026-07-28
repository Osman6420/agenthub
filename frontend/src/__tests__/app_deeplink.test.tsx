import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";

const draft = {
  id: 9,
  organization: "org-b",
  organization_id: 2,
  project_id: 4,
  scenario_id: null,
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
  revision: 1,
  can_write: false,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("builder deep link", () => {
  it("locks scenario context and creates a scenario draft from whole workflow JSON", async () => {
    const requests: { url: string; body?: Record<string, unknown> }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
      const value = String(url);
      const body = options?.body ? JSON.parse(String(options.body)) as Record<string, unknown> : undefined;
      requests.push({ url: value, body });
      let payload: unknown = {};
      if (value.includes("node-schema")) payload = {
        organization: "org-b", can_write: true,
        dsl: { api_version: "agenthub/v1", kind: "Workflow" },
        limits: { max_nodes: 50, max_edges: 100 },
        node_types: [
          { type: "input", label: "Input", category: "io", fields: [], is_entry: true },
          { type: "end", label: "End", category: "io", fields: [], is_terminal: true },
        ], tool_binding_roles: [], custom_nodes: [],
        projects: [{ id: 4, slug: "project", name: "Project" }],
      };
      else if (value.endsWith("/artifact-drafts/")) payload = { drafts: [] };
      else if (value.endsWith("/drafts/") && options?.method === "POST") payload = {
        ...draft, project_id: 4, scenario_id: 17, can_write: true, body: body?.body,
      };
      else if (value.endsWith("/drafts/")) payload = { drafts: [] };
      return new Response(JSON.stringify(payload), {
        status: options?.method === "POST" ? 201 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }));
    const workflow = draft.body;
    render(<App apiBase="/console/api/builder/"
      orgs={[{ slug: "org-b", name: "B", can_write: true }]}
      initial={{ organization: "org-b", project_id: 4, project_name: "Project",
        scenario_id: 17, scenario_name: "Support" }} />);

    await screen.findByText("Scenario Studio · Support");
    expect(screen.getByLabelText("organizasyon")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("draft adı"), { target: { value: "Imported" } });
    fireEvent.change(screen.getByLabelText("logical id"), { target: { value: "imported" } });
    fireEvent.change(screen.getByLabelText("logical artifact açıklaması"), {
      target: { value: "Imported workflow purpose" },
    });
    fireEvent.change(screen.getByLabelText("yeni workflow JSON"), {
      target: { value: JSON.stringify(workflow) },
    });
    fireEvent.click(screen.getByText("Oluştur"));
    await waitFor(() => expect(requests.some((request) => request.body?.scenario_id === 17)).toBe(true));
    const create = requests.find((request) => request.body?.scenario_id === 17)?.body;
    expect(create?.project_id).toBe(4);
    expect(create?.body).toEqual(workflow);
    await screen.findByText("Graph");
    expect(screen.getByText("JSON")).toBeInTheDocument();
  });

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
