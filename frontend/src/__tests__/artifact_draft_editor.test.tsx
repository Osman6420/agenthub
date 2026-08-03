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
  scenario_id: 4,
  name: "Girdi",
  logical_id: "input_v1",
  logical_description: "Input contract",
  body: { type: "object" },
  last_published_version: 0,
  last_published_at: null,
  updated_at: "2026-07-14T00:00:00Z",
  revision: 1,
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

  it("authors prompt text and requires a version note before immutable publish", async () => {
    const promptDraft: ArtifactDraft = {
      ...draft,
      artifact_type: "prompt_template",
      name: "Yanıt promptu",
      logical_id: "answer_prompt",
      logical_description: "Stable answer behavior",
      body: { template: "Yanıtla" },
    };
    const requests: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
      requests.push({ url: String(url), method: String(options?.method ?? "GET") });
      const published = String(url).endsWith("/publish/");
      return new Response(JSON.stringify(published ? {
        published: true,
        artifact_version_id: 91,
        artifact_type: "prompt_template",
        logical_id: "answer_prompt",
        logical_description: "Stable answer behavior",
        version: 2,
        version_description: "Wording",
        checksum: "b".repeat(64),
        revision: 2,
      } : { ...promptDraft, revision: 2, last_published_version: 2 }), {
        status: published ? 201 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }));
    const onPublished = vi.fn();
    render(<ArtifactDraftEditor api={new BuilderApi("/console/api/builder/")}
      draft={promptDraft} onChange={vi.fn()} onClose={vi.fn()} onPublished={onPublished} />);

    fireEvent.click(screen.getByText("Yayımla"));
    expect(screen.getByRole("alert")).toHaveTextContent("Bu sürümde nelerin değiştiğini yazın.");
    expect(screen.getByLabelText("artifact exact version açıklaması")).toHaveFocus();
    expect(requests).toEqual([]);

    fireEvent.change(screen.getByLabelText("prompt metni"), { target: { value: "Yeni yanıt" } });
    fireEvent.change(screen.getByLabelText("artifact exact version açıklaması"), {
      target: { value: "Wording" },
    });
    fireEvent.click(screen.getByText("Yayımla"));
    await waitFor(() => expect(onPublished).toHaveBeenCalledWith(
      expect.objectContaining({ artifact_version_id: 91, version: 2 }),
    ));
    expect(requests.map((item) => item.method)).toEqual(["PUT", "POST", "GET"]);
  });
});
