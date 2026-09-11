import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { defaultGovernedProfileBody, GovernedProfileEditor } from "../GovernedProfileEditor";

describe("GovernedProfileEditor", () => {
  it("edits only the closed retrieval fields and exposes no raw JSON escape hatch", () => {
    const onChange = vi.fn();
    render(<GovernedProfileEditor type="retrieval_profile"
      body={defaultGovernedProfileBody("retrieval_profile")} onChange={onChange} />);

    expect(screen.queryByRole("textbox", { name: /JSON/i })).not.toBeInTheDocument();
    // Chunking is document-set owned; Studio must not render a chunking editor at all.
    expect(screen.queryByLabelText("Parçalama stratejisi")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Arama sonuç sayısı"), { target: { value: "12" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      api_version: "agenthub/retrieval/v1",
      kind: "RetrievalProfile",
      top_k: 12,
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
