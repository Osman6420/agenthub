import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { BuilderApi } from "../api";
import { NewGovernedProfilePanel } from "../NewGovernedProfilePanel";

it("creates a model-profile artifact from a safe UUID-only platform choice", async () => {
  const profileId = "00000000-0000-0000-0000-000000000001";
  const requests: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
    const value = String(url);
    if (value.includes("model-profile-options")) {
      return new Response(JSON.stringify({
        options: [{
          profile_id: profileId,
          logical_id: "summary",
          revision: 2,
          provider: "openai_compatible",
          model: "summary-v2",
          max_output_tokens: 2048,
        }],
        limited: false,
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    requests.push({ url: value, body: JSON.parse(String(options?.body)) as unknown });
    return new Response(JSON.stringify({
      id: 31,
      draft_kind: "artifact",
      artifact_type: "model_profile",
      organization: "org",
      organization_id: 1,
      project_id: 2,
      scenario_id: 3,
      name: "Summary model",
      logical_id: "summary.model",
      logical_description: "Stable summary model",
      body: { profile_id: profileId },
      last_published_version: 0,
      last_published_at: null,
      updated_at: "2026-08-03T00:00:00Z",
      revision: 1,
      can_write: true,
    }), { status: 201, headers: { "Content-Type": "application/json" } });
  }));
  const onCreated = vi.fn();
  render(<NewGovernedProfilePanel api={new BuilderApi("/console/api/builder/")}
    organization="org" projectId={2} scenarioId={3} onCreated={onCreated} />);

  fireEvent.change(screen.getByLabelText("yeni profil türü"), {
    target: { value: "model_profile" },
  });
  await screen.findByRole("option", { name: /summary:r2/ });
  fireEvent.change(screen.getByLabelText("platform model profili"), {
    target: { value: profileId },
  });
  fireEvent.change(screen.getByLabelText("yeni profil adı"), {
    target: { value: "Summary model" },
  });
  fireEvent.change(screen.getByLabelText("yeni profil logical id"), {
    target: { value: "summary.model" },
  });
  fireEvent.change(screen.getByLabelText("yeni profil açıklaması"), {
    target: { value: "Stable summary model" },
  });
  expect(screen.getByText(/Endpoint ve secret alanları gösterilmez/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Profil taslağı oluştur"));

  await waitFor(() => expect(onCreated).toHaveBeenCalled());
  expect(requests).toHaveLength(1);
  expect(requests[0]?.body).toEqual(expect.objectContaining({
    artifact_type: "model_profile",
    body: { profile_id: profileId },
  }));
  expect(JSON.stringify(requests[0]?.body)).not.toContain("host");
  expect(JSON.stringify(requests[0]?.body)).not.toContain("secret");
});

it("offers no chunking profile: that artifact is owned by the document set", () => {
  render(<NewGovernedProfilePanel api={new BuilderApi("/console/api/builder/")}
    organization="org" projectId={2} scenarioId={3} onCreated={vi.fn()} />);

  const select = screen.getByLabelText("yeni profil türü") as HTMLSelectElement;
  expect([...select.options].map((option) => option.value)).toEqual([
    "retrieval_profile", "model_profile",
  ]);
  expect(screen.queryByText("Parçalama profili")).not.toBeInTheDocument();
  // The default selection must be a scenario-owned type, never a document-set one.
  expect(select.value).toBe("retrieval_profile");
});
