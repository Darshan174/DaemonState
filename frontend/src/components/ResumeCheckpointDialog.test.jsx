import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResumeCheckpointDialog from "./ResumeCheckpointDialog";


describe("ResumeCheckpointDialog", () => {
  it("does not present Claude's URL-handler launcher as Claude Desktop", () => {
    render(
      <ResumeCheckpointDialog
        checkpoint={{
          id: "checkpoint-1",
          provider: "claude",
          sections: { goal: [{ statement: "Continue the saved task" }] },
          boundary: {},
          currentness: {},
        }}
        isPending={false}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByText("Open Claude Code")).toBeInTheDocument();
    expect(screen.getByText(/URL-handler launcher alone cannot reopen/)).toBeInTheDocument();
    expect(screen.queryByText("Claude Desktop")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open Claude Code and copy context" }),
    ).toBeInTheDocument();
  });

  it("keeps the dialog cancellable", () => {
    const onCancel = vi.fn();
    render(
      <ResumeCheckpointDialog
        checkpoint={{
          id: "checkpoint-2",
          provider: "claude_code",
          sections: { goal: [{ statement: "Continue the saved task" }] },
          boundary: {},
          currentness: {},
        }}
        isPending={false}
        onCancel={onCancel}
        onConfirm={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
