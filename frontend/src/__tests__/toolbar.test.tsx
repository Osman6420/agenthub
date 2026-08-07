import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Toolbar } from "../components/Toolbar";
import type { BuilderController } from "../useBuilder";

function builderStub(): BuilderController {
  return {
    readOnly: false,
    isDirty: true,
    diagnostics: null,
    status: "",
    workflowId: "flow",
    setWorkflowId: vi.fn(),
  } as unknown as BuilderController;
}

describe("workflow publish feedback", () => {
  it("focuses and explains an empty version note instead of silently doing nothing", () => {
    const onAction = vi.fn();
    render(<Toolbar builder={builderStub()} draftName="Flow" busy={false} onAction={onAction} />);

    fireEvent.click(screen.getByText("Yalnızca yayımla"));
    expect(screen.getByRole("alert")).toHaveTextContent("Bu sürümde nelerin değiştiğini yazın.");
    expect(screen.getByLabelText("exact version açıklaması")).toHaveFocus();
    expect(onAction).not.toHaveBeenCalled();
  });

  it("offers publishing and verifying as one action", () => {
    const onAction = vi.fn();
    render(<Toolbar builder={builderStub()} draftName="Flow" busy={false} onAction={onAction} />);
    fireEvent.change(screen.getByLabelText("exact version açıklaması"), {
      target: { value: "ilk sürüm" },
    });

    fireEvent.click(screen.getByText("Yayımla ve test et"));

    expect(onAction).toHaveBeenCalledWith("publishAndVerify", "ilk sürüm");
  });

  it("still guards the combined action against a missing version note", () => {
    const onAction = vi.fn();
    render(<Toolbar builder={builderStub()} draftName="Flow" busy={false} onAction={onAction} />);

    fireEvent.click(screen.getByText("Yayımla ve test et"));

    expect(screen.getByRole("alert")).toHaveTextContent("Bu sürümde nelerin değiştiğini yazın.");
    expect(onAction).not.toHaveBeenCalled();
  });
});
