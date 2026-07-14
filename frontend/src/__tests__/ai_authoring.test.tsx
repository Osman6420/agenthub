import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AiAuthoringPanel } from "../AiAuthoringPanel";
import { BuilderApi } from "../api";

describe("AI authoring panel", () => {
  it("previews a candidate and transfers it only after explicit acceptance", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      calls.push(String(url));
      const accepted = String(url).endsWith("/accept/");
      return new Response(JSON.stringify(accepted ? {
        id: 7, organization: "org", organization_id: 1, project_id: null,
        name: "AI", logical_id: "ai_flow", body: {}, last_published_version: 0,
        last_published_at: null, can_write: true,
      } : { candidate: { kind: "Workflow" }, diagnostics: { ok: true, errors: [] } }),
      { status: accepted ? 201 : 200, headers: { "Content-Type": "application/json" } });
    }));
    const accepted = vi.fn();
    render(<AiAuthoringPanel api={new BuilderApi("/console/api/builder/")}
      organization="org" projects={[{ id: 3, name: "Project" }]} onAccepted={accepted} />);

    fireEvent.change(screen.getByLabelText("senaryo açıklaması"), { target: { value: "akış" } });
    fireEvent.click(screen.getByText("Aday üret"));
    await screen.findByText("Aday doğrulandı.");
    expect(calls).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("AI draft adı"), { target: { value: "AI" } });
    fireEvent.change(screen.getByLabelText("AI logical id"), { target: { value: "ai_flow" } });
    fireEvent.click(screen.getByText("Adayı draft'a aktar ve aç"));
    await waitFor(() => expect(accepted).toHaveBeenCalled());
    expect(calls).toHaveLength(2);
  });
});
