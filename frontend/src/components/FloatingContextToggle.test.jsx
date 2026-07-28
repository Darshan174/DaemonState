import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FloatingContextToggle from "./FloatingContextToggle";

const mocks = vi.hoisted(() => ({
  status: {
    data: { available: true, visible: false, workspace_id: null },
    isLoading: false,
    isError: false,
    error: null,
  },
  visibility: {
    isPending: false,
    error: null,
    mutate: vi.fn(),
  },
}));

vi.mock("../api/hooks", () => ({
  useDesktopOverlayStatus: () => mocks.status,
  useSetDesktopOverlayVisibility: () => mocks.visibility,
}));

beforeEach(() => {
  mocks.status.data = { available: true, visible: false, workspace_id: null };
  mocks.status.isLoading = false;
  mocks.status.isError = false;
  mocks.status.error = null;
  mocks.visibility.isPending = false;
  mocks.visibility.error = null;
  mocks.visibility.mutate.mockReset();
});

describe("FloatingContextToggle", () => {
  it("requests that the hidden control be shown for the active workspace", () => {
    render(<FloatingContextToggle workspaceId="workspace-1" />);

    const toggle = screen.getByRole("switch", {
      name: "Floating context control",
    });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("Off")).toBeInTheDocument();

    fireEvent.click(toggle);

    expect(mocks.visibility.mutate).toHaveBeenCalledWith({
      visible: true,
      workspaceId: "workspace-1",
    });
  });

  it("requests that the visible control be hidden without changing local state", () => {
    mocks.status.data = {
      available: true,
      visible: true,
      workspace_id: "workspace-2",
    };
    render(<FloatingContextToggle workspaceId="workspace-2" />);

    const toggle = screen.getByRole("switch", {
      name: "Floating context control",
    });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("On")).toBeInTheDocument();

    fireEvent.click(toggle);

    expect(mocks.visibility.mutate).toHaveBeenCalledWith({
      visible: false,
      workspaceId: "workspace-2",
    });
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("disables the switch while status is loading or a change is pending", () => {
    mocks.status.data = null;
    mocks.status.isLoading = true;
    const view = render(<FloatingContextToggle workspaceId="workspace-1" />);

    expect(screen.getByRole("switch", {
      name: "Floating context control",
    })).toBeDisabled();
    expect(screen.getByText("Checking…")).toBeInTheDocument();

    mocks.status.data = {
      available: true,
      visible: false,
      workspace_id: "workspace-1",
    };
    mocks.status.isLoading = false;
    mocks.visibility.isPending = true;
    view.rerender(<FloatingContextToggle workspaceId="workspace-1" />);

    expect(screen.getByRole("switch", {
      name: "Floating context control",
    })).toBeDisabled();
    expect(screen.getByText("Showing…")).toBeInTheDocument();
  });

  it("explains an unsupported runtime and does not issue a request", () => {
    mocks.status.data = {
      available: false,
      visible: false,
      message: "The floating control is available only on macOS.",
    };
    render(<FloatingContextToggle workspaceId="workspace-1" />);

    const toggle = screen.getByRole("switch", {
      name: "Floating context control",
    });
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveAccessibleDescription(
      "The floating control is available only on macOS.",
    );
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(mocks.visibility.mutate).not.toHaveBeenCalled();
  });

  it("announces a failed change while preserving the last server state", () => {
    mocks.status.data = {
      available: true,
      visible: true,
      workspace_id: "workspace-1",
    };
    mocks.visibility.error = new Error("The floating control could not be hidden.");
    render(<FloatingContextToggle workspaceId="workspace-1" />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The floating control could not be hidden.",
    );
    expect(screen.getByRole("switch", {
      name: "Floating context control",
    })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("On")).toBeInTheDocument();
  });

  it("offers to move a visible control from another project", () => {
    mocks.status.data = {
      available: true,
      visible: true,
      workspace_id: "workspace-1",
    };
    render(<FloatingContextToggle workspaceId="workspace-2" />);

    const toggle = screen.getByRole("switch", {
      name: "Floating context control",
    });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("Other project")).toBeInTheDocument();

    fireEvent.click(toggle);

    expect(mocks.visibility.mutate).toHaveBeenCalledWith({
      visible: true,
      workspaceId: "workspace-2",
    });
  });
});
