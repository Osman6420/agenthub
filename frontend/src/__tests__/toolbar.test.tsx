import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Toolbar } from "../components/Toolbar";
import type { BuilderController } from "../useBuilder";

describe("workflow publish feedback", () => {
  it("focuses and explains an empty version note instead of silently doing nothing", () => {
    const onAction = vi.fn();
    const builder = {
      readOnly: false,
      isDirty: true,
      diagnostics: null,
      status: "",
      workflowId: "flow",
      setWorkflowId: vi.fn(),
    } as unknown as BuilderController;
    render(<Toolbar builder={builder} draftName="Flow" busy={false} onAction={onAction} />);

    fireEvent.click(screen.getByText("Yayımla"));
    expect(screen.getByRole("alert")).toHaveTextContent("Bu sürümde nelerin değiştiğini yazın.");
    expect(screen.getByLabelText("exact version açıklaması")).toHaveFocus();
    expect(onAction).not.toHaveBeenCalled();
  });
});
