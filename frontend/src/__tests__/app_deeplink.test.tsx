import { render, screen, waitFor } from "@testing-library/react";
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
  it("shows AI authoring for an exact scenario editor without organization-wide write", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const value = String(url);
      let payload: unknown = {};
      if (value.includes("node-schema")) payload = {
        organization: "org-b", can_write: false,
        dsl: { api_version: "agenthub/v1", kind: "Workflow" },
        limits: { max_nodes: 50, max_edges: 100 }, node_types: [],
        tool_binding_roles: [], custom_nodes: [],
        projects: [{ id: 4, slug: "project", name: "Project" }],
      };
      else if (value.endsWith("/drafts/")) payload = { drafts: [] };
      else if (value.endsWith("/artifact-drafts/")) payload = { drafts: [] };
      return new Response(JSON.stringify(payload), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));

    render(<App apiBase="/console/api/builder/"
      orgs={[{ slug: "org-b", name: "B", can_write: false }]}
      initial={{ organization: "org-b", project_id: 4, project_name: "Project",
        scenario_id: 17, scenario_name: "Support", can_author_scenario: true,
        ai_authoring: { available: true, message: "AI authoring hazır" } }} />);

    expect(await screen.findByText("Scenario Studio AI planner")).toBeInTheDocument();
    expect(screen.getByText("AI authoring hazır")).toBeInTheDocument();
  });

  it("opens the scenario's single workflow directly, with no draft list or create form", async () => {
    const draftRow = {
      id: 9, organization: "org-b", organization_id: 2, project_id: 4, scenario_id: 17,
      name: "Support workflow", logical_id: "support_workflow", logical_description: "Purpose",
      body: { api_version: "agenthub/v1", kind: "Workflow", metadata: { id: "support_workflow" },
        spec: { input_node: "request", nodes: [{ id: "request", type: "input" },
          { id: "done", type: "end" }], edges: [{ from: "request", to: "done" }] } },
      last_published_version: 0, last_published_at: null, revision: 1, can_write: true,
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const value = String(url);
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
      else if (value.endsWith(`/drafts/${draftRow.id}/`)) payload = draftRow;
      else if (value.endsWith("/drafts/")) payload = { drafts: [draftRow] };
      return new Response(JSON.stringify(payload), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));

    render(<App apiBase="/console/api/builder/"
      orgs={[{ slug: "org-b", name: "B", can_write: true }]}
      initial={{ organization: "org-b", project_id: 4, project_name: "Project",
        scenario_id: 17, scenario_name: "Support" }} />);

    // The editor is the landing surface: no intermediate list, no naming ceremony.
    await screen.findByText("Graph");
    expect(screen.queryByText("Draft'lar")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("draft adı")).not.toBeInTheDocument();
    expect(screen.queryByText("Artifact taslakları")).not.toBeInTheDocument();
  });

  it("offers a way back to the scenario it was opened from", async () => {
    // Studio is a step inside the scenario journey, not a destination. Without this the
    // only way back is the browser's back button.
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const value = String(url);
      let payload: unknown = {};
      if (value.includes("node-schema")) payload = {
        organization: "org-b", can_write: true,
        dsl: { api_version: "agenthub/v1", kind: "Workflow" },
        limits: { max_nodes: 50, max_edges: 100 },
        node_types: [], tool_binding_roles: [], custom_nodes: [], projects: [],
      };
      else if (value.endsWith("/drafts/")) payload = { drafts: [] };
      return new Response(JSON.stringify(payload), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));

    render(<App apiBase="/console/api/builder/"
      orgs={[{ slug: "org-b", name: "B", can_write: true }]}
      initial={{ organization: "org-b", project_id: 4, project_name: "Project",
        scenario_id: 17, scenario_name: "Support",
        scenario_public_id: "7f1d2c34-0000-4000-8000-000000000001" }} />);

    const back = await screen.findByText("← Senaryoya dön");
    expect(back).toHaveAttribute(
      "href",
      "/console/scenarios/id/7f1d2c34-0000-4000-8000-000000000001/",
    );
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
