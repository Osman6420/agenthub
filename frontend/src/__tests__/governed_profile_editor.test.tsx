import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { defaultGovernedProfileBody, GovernedProfileEditor } from "../GovernedProfileEditor";

describe("GovernedProfileEditor", () => {
  it("edits only the closed chunking fields", () => {
    const onChange = vi.fn();
    render(<GovernedProfileEditor type="chunking_profile"
      body={defaultGovernedProfileBody("chunking_profile")} onChange={onChange} />);

    expect(screen.queryByRole("textbox", { name: /JSON/i })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Parçalama stratejisi"), {
      target: { value: "headings" },
    });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      api_version: "agenthub/chunking/v1",
      kind: "ChunkingProfile",
      strategy: "headings",
    }));
  });

  it("removes hybrid-only weights when retrieval mode changes", () => {
    const onChange = vi.fn();
    render(<GovernedProfileEditor type="retrieval_profile"
      body={defaultGovernedProfileBody("retrieval_profile")} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Arama modu"), { target: { value: "vector" } });
    expect(onChange).toHaveBeenCalledWith({
      api_version: "agenthub/retrieval/v1",
      kind: "RetrievalProfile",
      mode: "vector",
      top_k: 8,
      score_threshold: 0,
    });
  });

  it("disables all profile inputs in read-only mode", () => {
    render(<GovernedProfileEditor type="retrieval_profile"
      body={defaultGovernedProfileBody("retrieval_profile")} onChange={vi.fn()} readOnly />);
    expect(screen.getByLabelText("Arama modu")).toBeDisabled();
    expect(screen.getByLabelText("Arama sonuç sayısı")).toBeDisabled();
  });
});
