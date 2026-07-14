import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArtifactDraftEditor } from "../ArtifactDraftEditor";
import { BuilderApi } from "../api";
import type { ArtifactDraft } from "../types";

const draft: ArtifactDraft = {
  id: 8,
  draft_kind: "artifact",
  artifact_type: "input_contract",
  organization: "org",
  organization_id: 1,
  project_id: 3,
  name: "Girdi",
  logical_id: "input_v1",
  body: { type: "object" },
  updated_at: "2026-07-14T00:00:00Z",
  can_write: true,
};

describe("artifact draft editor", () => {
  it("validates and saves through the governed artifact-draft API", async () => {
    const requests: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
      requests.push({ url: String(url), method: String(options?.method) });
      const diagnostics = String(url).endsWith("/diagnostics/");
      return new Response(JSON.stringify(diagnostics
        ? { ok: true, errors: [], compiled_checksum: "a".repeat(64) }
        : { ...draft, name: "Girdi v2" }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));
    const onChange = vi.fn();
    render(<ArtifactDraftEditor api={new BuilderApi("/console/api/builder/")} draft={draft}
      onChange={onChange} onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("sözleşme taslak adı"), {
      target: { value: "Girdi v2" },
    });
    fireEvent.click(screen.getByText("Doğrula"));
    await screen.findByText("Taslak doğrulandı.");
    fireEvent.click(screen.getByText("Kaydet"));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(requests).toEqual([
      { url: "/console/api/builder/artifact-drafts/8/diagnostics/", method: "POST" },
      { url: "/console/api/builder/artifact-drafts/8/", method: "PUT" },
    ]);
  });

  it("blocks malformed JSON before making a request", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<ArtifactDraftEditor api={new BuilderApi("/console/api/builder/")} draft={draft}
      onChange={vi.fn()} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("sözleşme JSON içeriği"), {
      target: { value: "not-json" },
    });
    fireEvent.click(screen.getByText("Doğrula"));
    expect(screen.getByRole("alert")).toHaveTextContent("Geçerli bir JSON nesnesi girin.");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
