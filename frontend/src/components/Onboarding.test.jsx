import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Onboarding from "./Onboarding";

const mocks = vi.hoisted(() => ({
  seedDemoMutate: vi.fn(),
  uploadMutateAsync: vi.fn(),
  setSelectedId: vi.fn(),
}));

vi.mock("../api/hooks", () => ({
  useSeedDemoData: () => ({ mutate: mocks.seedDemoMutate }),
  useUploadSourceFile: () => ({ mutateAsync: mocks.uploadMutateAsync }),
}));

vi.mock("../context/WorkspaceContext", () => ({
  useWorkspaceSelection: () => ({
    selectedId: "workspace-1",
    setSelectedId: mocks.setSelectedId,
  }),
}));

function renderOnboarding() {
  return render(
    <MemoryRouter>
      <Onboarding />
    </MemoryRouter>,
  );
}

describe("Onboarding", () => {
  beforeEach(() => {
    mocks.seedDemoMutate.mockReset();
    mocks.uploadMutateAsync.mockReset();
    mocks.setSelectedId.mockReset();
  });

  it("shows honest launch-available demo and connector copy", () => {
    renderOnboarding();

    expect(screen.getByText("Run Demo Workspace")).toBeInTheDocument();
    expect(screen.getByText(/GitHub, Slack, Gmail, Google Drive, and Codex/)).toBeInTheDocument();
    expect(screen.getByText(/Slack, GitHub, Gmail, or Google Drive/)).toBeInTheDocument();
    expect(screen.queryByText(/Notion|Zoom/)).not.toBeInTheDocument();
  });

  it("starts the demo seed against the selected workspace", () => {
    mocks.seedDemoMutate.mockImplementation(() => {});
    renderOnboarding();

    fireEvent.click(screen.getByRole("button", { name: /start demo/i }));

    expect(mocks.seedDemoMutate).toHaveBeenCalledWith(
      { workspaceId: "workspace-1" },
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );
    expect(screen.getByText(/source-backed demo context from GitHub, Slack, Gmail, Google Drive, and Codex/)).toBeInTheDocument();
  });
});
