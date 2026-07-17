import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import OpenLoopsPanel from "./OpenLoopsPanel";

vi.mock("../../api/client", () => ({ api: { get: vi.fn() } }));

const loops = [{
  id: "loop-warning",
  focus_component_id: "component-warning",
  status: "open",
  severity: "warning",
  title: "Completion has no verification",
  explanation: "The agent claimed completion without a required result.",
  next_action: "Run the required check.",
  last_seen_at: "2026-07-15T05:00:00Z",
  sources: [{ source_document_id: "source-warning", excerpt: "Completion claimed." }],
}, {
  id: "loop-critical",
  status: "open",
  severity: "critical",
  title: "Required verification failed",
  explanation: "pytest exited with code 1.",
}, {
  id: "loop-closed",
  status: "resolved",
  severity: "warning",
  title: "Old blocker",
}];

describe("OpenLoopsPanel", () => {
  beforeEach(() => api.get.mockReset());

  it("keeps unresolved loops visible, orders critical first, and collapses closed history", () => {
    const { container } = render(<OpenLoopsPanel data={{ open_count: 2, items: loops }} onClose={() => {}} />);
    const cards = [...container.querySelectorAll("[data-open-loop-state]")];

    expect(screen.getByRole("heading", { name: "Unresolved work" })).toBeInTheDocument();
    expect(screen.getByText(/Evidence-backed problems/)).toBeInTheDocument();
    expect(screen.queryByText("Open loops")).not.toBeInTheDocument();
    expect(cards[0]).toHaveTextContent("Required verification failed");
    expect(cards[1]).toHaveTextContent("Completion has no verification");
    const closed = screen.getByText("Closed · 1").closest("details");
    expect(closed).not.toHaveAttribute("open");
  });

  it("uses a clear empty state when no evidence-backed problem exists", () => {
    render(<OpenLoopsPanel data={{ items: [] }} onClose={() => {}} />);

    expect(screen.getByText("Nothing unresolved")).toBeInTheDocument();
    expect(screen.getByText("No evidence-backed problem currently needs action.")).toBeInTheDocument();
  });

  it("requires an auditable reason before resolving a loop", async () => {
    const onUpdate = vi.fn().mockResolvedValue({ status: "resolved" });
    render(<OpenLoopsPanel data={{ items: [loops[1]] }} onClose={() => {}} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm resolve" }));
    expect(screen.getByRole("alert")).toHaveTextContent("reason is required");
    expect(onUpdate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Reason for resolving"), { target: { value: "The required check now passes." } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm resolve" }));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith({
      loopId: "loop-critical",
      action: "resolve",
      reason: "The required check now passes.",
    }));
  });

  it("opens durable source evidence and returns focus to the caller contract", async () => {
    api.get.mockResolvedValue({ content: "Exact completion claim." });
    const onOpenFocus = vi.fn();
    render(<OpenLoopsPanel data={{ items: [loops[0]] }} workspaceId="workspace-1" onClose={() => {}} onOpenFocus={onOpenFocus} />);

    fireEvent.click(screen.getByRole("button", { name: "Open task" }));
    expect(onOpenFocus).toHaveBeenCalledWith("component-warning");
    fireEvent.click(screen.getByRole("button", { name: "View evidence 1" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/sources/source-warning?workspace_id=workspace-1"));
    expect(await screen.findByText("Exact completion claim.")).toBeInTheDocument();
  });

  it("assigns an open loop with an auditable reason", async () => {
    const onUpdate = vi.fn().mockResolvedValue({ status: "open", assigned_to: "darshan" });
    render(<OpenLoopsPanel data={{ items: [loops[1]] }} onClose={() => {}} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    fireEvent.change(screen.getByLabelText("Assignee"), { target: { value: "darshan" } });
    fireEvent.change(screen.getByLabelText("Reason for assigning"), { target: { value: "Own the failing verification." } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm assign" }));

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith({
      loopId: "loop-critical",
      action: "assign",
      reason: "Own the failing verification.",
      assignee: "darshan",
    }));
  });

  it("keeps pending verified playbooks reviewable without another page", async () => {
    const onUpdatePlaybook = vi.fn().mockResolvedValue({ status: "approved" });
    render(
      <OpenLoopsPanel
        data={{ items: [] }}
        playbooks={[{
          id: "playbook-1",
          status: "pending_review",
          objective_pattern: "Add a connector",
          successful_run_count: 1,
          ordered_steps: ["Register the connector", "Run connector tests"],
        }]}
        onClose={() => {}}
        onUpdatePlaybook={onUpdatePlaybook}
      />,
    );

    expect(screen.getByText("Reusable agent steps to review")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.change(screen.getByLabelText("Reason for approving"), { target: { value: "Steps match the accepted implementation." } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm approve" }));
    await waitFor(() => expect(onUpdatePlaybook).toHaveBeenCalledWith({
      playbookId: "playbook-1",
      action: "approve",
      reason: "Steps match the accepted implementation.",
    }));
  });
});
