import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AiAuthoringPanel } from "../AiAuthoringPanel";
import { BuilderApi } from "../api";

describe("AI authoring panel", () => {
  it("previews a candidate and transfers it only after explicit acceptance", async () => {
    const calls: string[] = [];
    const bodies: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
      calls.push(String(url));
      bodies.push(JSON.parse(String(options?.body ?? "{}")) as Record<string, unknown>);
      const accepted = String(url).endsWith("/accept/");
      return new Response(JSON.stringify(accepted ? {
        id: 7, organization: "org", organization_id: 1, project_id: null,
        scenario_id: null,
        name: "AI", logical_id: "ai_flow", body: {}, last_published_version: 0,
        last_published_at: null, revision: 1, can_write: true,
      } : {
        artifact_type: "workflow_definition", candidate: { kind: "Workflow" },
        diagnostics: { ok: true, errors: [] },
        prompt_contract: { id: "agenthub.workflow-authoring", revision: 1, checksum: "a".repeat(64) },
      }),
      { status: accepted ? 201 : 200, headers: { "Content-Type": "application/json" } });
    }));
    const accepted = vi.fn();
    render(<AiAuthoringPanel api={new BuilderApi("/console/api/builder/")}
      organization="org" projects={[{ id: 3, name: "Project" }]} lockedProjectId={3}
      scenarioId={17} onAccepted={accepted} />);

    fireEvent.change(screen.getByLabelText("taslak açıklaması"), { target: { value: "akış" } });
    fireEvent.click(screen.getByText("Aday üret"));
    await screen.findByText("Aday doğrulandı.");
    expect(calls).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("AI taslak adı"), { target: { value: "AI" } });
    fireEvent.change(screen.getByLabelText("AI logical id"), { target: { value: "ai_flow" } });
    fireEvent.click(screen.getByText("Adayı taslağa aktar ve aç"));
    await waitFor(() => expect(accepted).toHaveBeenCalled());
    expect(calls).toHaveLength(2);
    expect(bodies[1].project_id).toBe(3);
    expect(bodies[1].scenario_id).toBe(17);
  });

  it("transfers a JSON contract to an artifact draft without opening the workflow editor", async () => {
    const requests: { url: string; body: Record<string, unknown> }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body ?? "{}")) as Record<string, unknown>;
      requests.push({ url: String(url), body });
      const accepted = String(url).endsWith("/accept/");
      return new Response(JSON.stringify(accepted ? {
        id: 8, draft_kind: "artifact", artifact_type: "input_contract",
        organization: "org", organization_id: 1, project_id: 3,
        name: "Girdi", logical_id: "input_v1", body: { type: "object" },
        updated_at: "2026-07-16T00:00:00Z", revision: 1, can_write: true,
      } : {
        artifact_type: "input_contract", candidate: { type: "object" },
        diagnostics: { ok: true, errors: [], compiled_checksum: "b".repeat(64) },
        prompt_contract: { id: "agenthub.input-contract-authoring", revision: 1, checksum: "c".repeat(64) },
      }), { status: accepted ? 201 : 200, headers: { "Content-Type": "application/json" } });
    }));
    const accepted = vi.fn();
    render(<AiAuthoringPanel api={new BuilderApi("/console/api/builder/")}
      organization="org" projects={[{ id: 3, name: "Project" }]} onAccepted={accepted} />);

    fireEvent.change(screen.getByLabelText("taslak türü"), { target: { value: "input_contract" } });
    fireEvent.change(screen.getByLabelText("taslak açıklaması"), { target: { value: "girdi" } });
    fireEvent.click(screen.getByText("Aday üret"));
    await screen.findByText("Aday doğrulandı.");
    fireEvent.change(screen.getByLabelText("AI taslak adı"), { target: { value: "Girdi" } });
    fireEvent.change(screen.getByLabelText("AI logical id"), { target: { value: "input_v1" } });
    fireEvent.click(screen.getByText("Adayı sözleşme taslağına aktar"));

    await waitFor(() => expect(accepted).toHaveBeenCalled());
    expect(requests[0].body.artifact_type).toBe("input_contract");
    expect(requests[1].body.artifact_type).toBe("input_contract");
    expect(requests[1].body.prompt_contract).toEqual({
      id: "agenthub.input-contract-authoring", revision: 1, checksum: "c".repeat(64),
    });
  });
});
