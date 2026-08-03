import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BuilderApi } from "../api";
import { ScenarioManifestPanel } from "../ScenarioManifestPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Scenario Studio exact candidate manifest", () => {
  it("shows a selected prompt inline, publishes a changed version, and adds it", async () => {
    let published = false;
    let mutationCount = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
      const value = String(url);
      let payload: unknown;
      if (value.includes("artifact-versions/12")) {
        payload = {
          id: 12, artifact_type: "prompt_template", logical_id: "answer_prompt",
          logical_description: "Stable answer behavior", version: 2,
          version_description: "Tone update", checksum: "b".repeat(64),
          body: { template: "UPDATED_PROMPT_TEXT" }, body_too_large: false,
          can_create_new_version: false,
        };
      } else if (value.includes("artifact-versions/7")) {
        payload = {
          id: 7,
          artifact_type: "prompt_template",
          logical_id: "answer_prompt",
          logical_description: "Stable answer behavior",
          version: 1,
          version_description: "Initial",
          checksum: "a".repeat(64),
          body: { template: "PRIVATE_PROMPT_TEXT" },
          body_too_large: false,
          can_create_new_version: true,
        };
      } else if (value.includes("/artifact-drafts/9/publish/")) {
        mutationCount += 1;
        published = true;
        payload = {
          published: true, artifact_version_id: 12, artifact_type: "prompt_template",
          logical_id: "answer_prompt", logical_description: "Stable answer behavior",
          version: 2, version_description: "Tone update", checksum: "b".repeat(64), revision: 3,
        };
      } else if (value.includes("/artifact-drafts/9/")) {
        mutationCount += 1;
        payload = {
          id: 9, draft_kind: "artifact", artifact_type: "prompt_template",
          organization: "org", organization_id: 1, project_id: 2, scenario_id: 3,
          name: "answer_prompt prompt", logical_id: "answer_prompt",
          logical_description: "Stable answer behavior", body: { template: "UPDATED_PROMPT_TEXT" },
          last_published_version: 0, last_published_at: null,
          updated_at: "2026-08-03T00:00:00Z", revision: 2, can_write: true,
        };
      } else if (value.endsWith("/artifact-drafts/")) {
        mutationCount += 1;
        payload = {
          id: 9,
          draft_kind: "artifact",
          artifact_type: "prompt_template",
          organization: "org",
          organization_id: 1,
          project_id: 2,
          scenario_id: 3,
          name: "answer_prompt prompt",
          logical_id: "answer_prompt",
          logical_description: "Stable answer behavior",
          body: { template: "PRIVATE_PROMPT_TEXT" },
          last_published_version: 0,
          last_published_at: null,
          updated_at: "2026-08-03T00:00:00Z",
          revision: 1,
          can_write: true,
        };
      } else if (value.includes("artifact_type=prompt_template") &&
        value.includes("logical_id=answer_prompt")) {
        payload = {
          level: "exact_version",
          roles: ["prompt_template"],
          options: published ? [{
            id: 12, version: 2, description: "Tone update", checksum: "b".repeat(64),
            status: "published", pinned_release_count: 0,
          }, {
            id: 7, version: 1, description: "Initial", checksum: "a".repeat(64),
            status: "published", pinned_release_count: 0,
          }] : [{ id: 7, version: 1, description: "Initial", checksum: "a".repeat(64),
            status: "published", pinned_release_count: 0 }],
        };
      } else if (value.includes("artifact_type=prompt_template")) {
        payload = {
          level: "logical_artifact",
          options: [{
            value: "answer_prompt", label: "answer_prompt",
            description: "Stable answer behavior", latest_version: 1,
          }],
        };
      } else {
        payload = {
          level: "artifact_type",
          options: [{ value: "prompt_template", label: "Prompt", description: "Prompt" }],
        };
      }
      return new Response(JSON.stringify(payload), {
        status: options?.method === "POST" ? 201 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }));
    render(<ScenarioManifestPanel api={new BuilderApi("/console/api/builder/")}
      scenarioPublicId="scenario" optionsUrl="/artifact-options/" organization="org"
      projectId={2} scenarioId={3} />);

    await screen.findByRole("option", { name: "Prompt" });
    fireEvent.change(screen.getByLabelText("Manifest artifact türü"), {
      target: { value: "prompt_template" },
    });
    await screen.findByRole("option", { name: "answer_prompt" });
    fireEvent.change(screen.getByLabelText("Manifest mantıksal artifactı"), {
      target: { value: "answer_prompt" },
    });
    await screen.findByRole("option", { name: /v1/ });
    fireEvent.change(screen.getByLabelText("Manifest kesin sürümü"), {
      target: { value: "7" },
    });
    const prompt = await screen.findByLabelText("Seçili prompt metni");
    expect(prompt).toHaveValue("PRIVATE_PROMPT_TEXT");
    expect(screen.queryByLabelText("Manifest rolü")).not.toBeInTheDocument();
    expect(screen.queryByText("Artifact içeriğini aç")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Bu exact sürümü ekle"));
    expect(screen.getAllByText(/answer_prompt:v1/).length).toBeGreaterThan(0);
    fireEvent.change(prompt, { target: { value: "UPDATED_PROMPT_TEXT" } });
    fireEvent.click(screen.getByText("Yeni sürümü yayımla ve ekle"));
    expect(mutationCount).toBe(0);
    expect(screen.getByLabelText("Prompt sürüm değişiklikleri")).toHaveFocus();
    expect(screen.getByText("Bu sürümde nelerin değiştiğini yazın.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Prompt sürüm değişiklikleri"), {
      target: { value: "Tone update" },
    });
    fireEvent.click(screen.getByText("Yeni sürümü yayımla ve ekle"));
    expect(await screen.findByText(/answer_prompt:v2/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/answer_prompt:v1/)).not.toBeInTheDocument());
    expect(screen.getByText(/Yeni immutable prompt v2 yayımlandı/)).toBeInTheDocument();
  });

  it("selects the newly published exact version when the picker remounts", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const parsed = new URL(String(url), window.location.origin);
      const type = parsed.searchParams.get("artifact_type");
      const logical = parsed.searchParams.get("logical_id");
      let payload: unknown;
      if (parsed.pathname.includes("artifact-versions/12")) {
        payload = {
          id: 12, artifact_type: "prompt_template", logical_id: "answer_prompt",
          logical_description: "Stable answer behavior", version: 2,
          version_description: "Updated", checksum: "b".repeat(64),
          body: { template: "Updated" }, body_too_large: false,
          can_create_new_version: false,
        };
      } else if (!type) {
        payload = {
          level: "artifact_type",
          options: [{ value: "prompt_template", label: "Prompt", description: "Prompt" }],
        };
      } else if (!logical) {
        payload = {
          level: "logical_artifact",
          options: [{
            value: "answer_prompt", label: "answer_prompt",
            description: "Stable answer behavior", latest_version: 2,
          }],
        };
      } else {
        payload = {
          level: "exact_version",
          roles: ["prompt_template"],
          options: [{
            id: 12, version: 2, description: "Updated", checksum: "b".repeat(64),
            status: "published", pinned_release_count: 0,
          }],
        };
      }
      return new Response(JSON.stringify(payload), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));

    render(<ScenarioManifestPanel api={new BuilderApi("/console/api/builder/")}
      scenarioPublicId="scenario" optionsUrl="/artifact-options/"
      refreshArtifact={{ id: 12, artifactType: "prompt_template", logicalId: "answer_prompt" }} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Manifest artifact türü")).toHaveValue("prompt_template");
      expect(screen.getByLabelText("Manifest mantıksal artifactı")).toHaveValue("answer_prompt");
      expect(screen.getByLabelText("Manifest kesin sürümü")).toHaveValue("12");
    });
    expect(await screen.findByLabelText("Seçili prompt metni")).toHaveAttribute("readonly");
  });

  it("preserves selected exact pins when canonical preflight and compile fail", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
      const value = String(url);
      calls.push(value);
      let payload: unknown;
      if (value.includes("artifact-versions/")) {
        const isTool = value.includes("/43/");
        payload = {
          id: isTool ? 43 : 42,
          artifact_type: isTool ? "tool_binding" : "workflow_definition",
          logical_id: isTool ? "search_binding" : "support_flow",
          logical_description: isTool ? "Search tool" : "Support",
          version: isTool ? 1 : 2,
          version_description: isTool ? "Search v1" : "Adds validation",
          checksum: (isTool ? "b" : "a").repeat(64),
          body: isTool ? { tool: "search" } : { definition: { nodes: [] } },
          body_too_large: false,
          can_create_new_version: false,
        };
      } else if (value.includes("release-manifest/preflight")) {
        payload = {
          ok: false,
          diagnostics: [{
            code: "workflow_missing",
            message: "Canonical workflow eksik.",
            role: "workflow_definition",
            artifact_type: "workflow_definition",
          }],
        };
      } else if (value.includes("release-manifest/requirements")) {
        payload = {
          ok: true,
          diagnostics: [],
          workflow: {
            artifact_version_id: 42,
            logical_id: "support_flow",
            version: 2,
            checksum: "a".repeat(64),
          },
          requirements: [
            { role: "workflow_definition", artifact_type: "workflow_definition", node_ids: [] },
            { role: "tool_binding.search", artifact_type: "tool_binding", node_ids: ["search"] },
          ],
        };
      } else if (value.includes("release-manifest/compile")) {
        payload = {
          ok: false,
          diagnostics: [{
            code: "workflow_compile_failed",
            message: "Workflow geçersiz.",
            role: "workflow_definition",
          }],
        };
      } else {
        const parsed = new URL(value, window.location.origin);
        const type = parsed.searchParams.get("artifact_type");
        const logical = parsed.searchParams.get("logical_id");
        if (!type) {
          payload = {
            level: "artifact_type",
            options: [
              { value: "workflow_definition", label: "Workflow", description: "Graph" },
              { value: "tool_binding", label: "Tool binding", description: "Tool" },
            ],
          };
        } else if (!logical) {
          const isTool = type === "tool_binding";
          payload = {
            level: "logical_artifact",
            artifact_type: type,
            options: [{
              value: isTool ? "search_binding" : "support_flow",
              label: isTool ? "search_binding" : "support_flow",
              description: isTool ? "Search tool" : "Support",
              latest_version: isTool ? 1 : 2,
            }],
          };
        } else {
          const isTool = type === "tool_binding";
          payload = {
            level: "exact_version",
            artifact_type: type,
            logical_id: logical,
            logical_description: isTool ? "Search tool" : "Support",
            roles: [isTool ? "tool_binding" : "workflow_definition"],
            options: [{
              id: isTool ? 43 : 42,
              version: isTool ? 1 : 2,
              description: isTool ? "Search v1" : "Adds validation",
              checksum: (isTool ? "b" : "a").repeat(64),
              status: "published",
              pinned_release_count: 0,
            }],
          };
        }
      }
      return new Response(JSON.stringify(payload), {
        status: options?.method === "POST" ? 200 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }));

    render(<ScenarioManifestPanel
      api={new BuilderApi("/console/api/builder/")}
      scenarioPublicId="11111111-1111-1111-1111-111111111111"
      optionsUrl="/console/scenarios/id/11111111-1111-1111-1111-111111111111/artifact-options/"
    />);

    await screen.findByRole("option", { name: "Workflow" });
    fireEvent.change(screen.getByLabelText("Manifest artifact türü"), {
      target: { value: "workflow_definition" },
    });
    await screen.findByRole("option", { name: "support_flow" });
    fireEvent.change(screen.getByLabelText("Manifest mantıksal artifactı"), {
      target: { value: "support_flow" },
    });
    await screen.findByRole("option", { name: /v2/ });
    fireEvent.change(screen.getByLabelText("Manifest kesin sürümü"), {
      target: { value: "42" },
    });
    fireEvent.click(await screen.findByText("Bu exact sürümü ekle"));

    expect(screen.getAllByText("workflow_definition").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/support_flow:v2/).length).toBeGreaterThan(0);
    expect(await screen.findByText("tool_binding.search")).toBeInTheDocument();
    expect(screen.getByText(/node search/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Bu rol için artifact seç"));
    await screen.findByRole("option", { name: "search_binding" });
    fireEvent.change(screen.getByLabelText("Manifest mantıksal artifactı"), {
      target: { value: "search_binding" },
    });
    await screen.findByRole("option", { name: /v1/ });
    fireEvent.change(screen.getByLabelText("Manifest kesin sürümü"), {
      target: { value: "43" },
    });
    fireEvent.click(await screen.findByText("Bu exact sürümü ekle"));
    expect(screen.getAllByText(/search_binding:v1/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByText("Kanonik ön kontrol"));
    await screen.findByText(/Kanonik ön kontrol düzeltme gerektiriyor/);
    expect(screen.getAllByText(/support_flow:v2/).length).toBeGreaterThan(0);
    expect(screen.getByText(/workflow_missing/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Candidate release derle"));
    await screen.findByText(/Candidate oluşturulmadı/);
    expect(screen.getAllByText(/support_flow:v2/).length).toBeGreaterThan(0);
    expect(screen.getByText(/workflow_compile_failed/)).toBeInTheDocument();
    await waitFor(() => expect(calls.some((url) => url.includes("release-manifest/compile"))).toBe(true));
  });

  it("shows the created candidate without clearing the manifest", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const value = String(url);
      let payload: unknown;
      if (value.includes("artifact-versions/7")) {
        payload = {
          id: 7, artifact_type: "workflow_definition", logical_id: "flow",
          logical_description: "Flow", version: 1, version_description: "First",
          checksum: "a".repeat(64), body: { definition: { nodes: [] } },
          body_too_large: false, can_create_new_version: false,
        };
      } else if (value.includes("release-manifest/compile")) {
        payload = {
          ok: true,
          diagnostics: [],
          release: {
            id: 17,
            status: "candidate",
            artifact_manifest_sha256: "b".repeat(64),
          },
        };
      } else if (value.includes("release-manifest/requirements")) {
        payload = {
          ok: true,
          diagnostics: [],
          requirements: [
            { role: "workflow_definition", artifact_type: "workflow_definition", node_ids: [] },
          ],
        };
      } else if (value.includes("artifact_type=workflow_definition") &&
        value.includes("logical_id=flow")) {
        payload = {
          level: "exact_version",
          roles: ["workflow_definition"],
          options: [{
            id: 7, version: 1, description: "First", checksum: "a".repeat(64),
            status: "published", pinned_release_count: 0,
          }],
        };
      } else if (value.includes("artifact_type=workflow_definition")) {
        payload = {
          level: "logical_artifact",
          options: [{ value: "flow", label: "flow", description: "Flow", latest_version: 1 }],
        };
      } else {
        payload = {
          level: "artifact_type",
          options: [{ value: "workflow_definition", label: "Workflow", description: "Graph" }],
        };
      }
      return new Response(JSON.stringify(payload), {
        status: value.includes("release-manifest/compile") ? 201 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }));
    render(<ScenarioManifestPanel api={new BuilderApi("/console/api/builder/")}
      scenarioPublicId="scenario" optionsUrl="/artifact-options/" />);

    await screen.findByRole("option", { name: "Workflow" });
    fireEvent.change(screen.getByLabelText("Manifest artifact türü"), {
      target: { value: "workflow_definition" },
    });
    await screen.findByRole("option", { name: "flow" });
    fireEvent.change(screen.getByLabelText("Manifest mantıksal artifactı"), {
      target: { value: "flow" },
    });
    await screen.findByRole("option", { name: /v1/ });
    fireEvent.change(screen.getByLabelText("Manifest kesin sürümü"), {
      target: { value: "7" },
    });
    fireEvent.click(await screen.findByText("Bu exact sürümü ekle"));
    fireEvent.click(screen.getByText("Candidate release derle"));

    expect(await screen.findByText("Candidate #17 aç")).toHaveAttribute(
      "href", "/console/releases/17/",
    );
    expect(screen.getAllByText(/flow:v1/).length).toBeGreaterThan(0);
  });

  it("loads a recommendation and exposes explicit dirty-state choices", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const value = String(url);
      let payload: unknown;
      if (value.includes("release-manifest/compile")) {
        payload = {
          ok: true,
          diagnostics: [],
          release: { id: 23, status: "candidate", artifact_manifest_sha256: "c".repeat(64) },
        };
      } else if (value.includes("preset=minimum")) {
        payload = {
          level: "preset",
          recommendation_only: true,
          missing_roles: ["eval_suite"],
          options: [{
            artifact_version_id: 11,
            role: "workflow_definition",
            artifactType: "workflow_definition",
            logicalId: "recommended-flow",
            version: 3,
            checksum: "d".repeat(64),
            description: "Recommended exact workflow",
          }],
        };
      } else {
        payload = { level: "artifact_type", options: [] };
      }
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }));
    render(<ScenarioManifestPanel api={new BuilderApi("/console/api/builder/")}
      scenarioPublicId="scenario" optionsUrl="/artifact-options/" />);

    fireEvent.click(screen.getByText("Minimum release önerisini getir"));

    expect(await screen.findByText(/recommended-flow:v3/)).toBeInTheDocument();
    expect(screen.getByText(/eksik roller: eval_suite/)).toBeInTheDocument();
    expect(screen.getByText("Candidate olarak kaydet")).toBeInTheDocument();
    expect(screen.getByText("Seçimi sil")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Düzenlemeye devam et"));
    expect(screen.queryByText("Candidate olarak kaydet")).not.toBeInTheDocument();
    expect(screen.getByText(/recommended-flow:v3/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Minimum release önerisini getir"));
    fireEvent.click(await screen.findByText("Candidate olarak kaydet"));
    expect(await screen.findByText("Candidate #23 aç")).toBeInTheDocument();
    expect(screen.queryByText("Seçimi sil")).not.toBeInTheDocument();
  });
});
