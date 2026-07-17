import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AiAuthoringPanel } from "../AiAuthoringPanel";
import { BuilderApi } from "../api";

describe("Studio AI authoring panel", () => {
  it("returns a transient candidate without asking for a name or logical id", async () => {
    const bodies: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn((_url: string, options?: RequestInit) => {
      bodies.push(JSON.parse(String(options?.body ?? "{}")) as Record<string, unknown>);
      return Promise.resolve(new Response(JSON.stringify({
        status: "workflow_candidate",
        artifact_type: "workflow_definition",
        candidate: { api_version: "agenthub/v1", kind: "Workflow" },
        diagnostics: { ok: false, errors: [{ code: "invalid_workflow", message: "incomplete" }] },
        prompt_contract: { id: "agenthub.workflow-authoring", revision: 1, checksum: "a".repeat(64) },
        authoring_context: { contract: "agenthub.studio-authoring-context/v1", checksum: "b".repeat(64) },
      }), { status: 200 }));
    }));
    const onGenerated = vi.fn();
    render(<AiAuthoringPanel api={new BuilderApi("/console/api/builder/")}
      organization="org" projects={[{ id: 3, name: "Project" }]}
      lockedProjectId={3} scenarioId={7} onGenerated={onGenerated} />);

    fireEvent.change(screen.getByLabelText("taslak açıklaması"), { target: { value: "akış" } });
    fireEvent.click(screen.getByText("Geçici aday üret"));

    await vi.waitFor(() => expect(onGenerated).toHaveBeenCalledOnce());
    expect(bodies[0]).toMatchObject({ project_id: 3, scenario_id: 7, description: "akış" });
    expect(screen.queryByLabelText(/logical/i)).not.toBeInTheDocument();
  });

  it("keeps capability-missing suggestions transient", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      status: "capability_missing",
      required_capability: "number.multiply",
      suggestion: { display_name: "Sayıyı çarp" },
      authoring_context: { contract: "agenthub.studio-authoring-context/v1", checksum: "b".repeat(64) },
    }), { status: 200 }))));
    const onGenerated = vi.fn();
    render(<AiAuthoringPanel api={new BuilderApi("/console/api/builder/")}
      organization="org" projects={[{ id: 3, name: "Project" }]}
      scenarioId={7} onGenerated={onGenerated} />);
    fireEvent.change(screen.getByLabelText("taslak açıklaması"), { target: { value: "çarp" } });
    fireEvent.click(screen.getByText("Geçici aday üret"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Eksik yetenek: number.multiply");
    expect(onGenerated).not.toHaveBeenCalled();
  });
});
