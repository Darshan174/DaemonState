import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SourceManager from "./SourceManager";
import { api } from "../api/client";

const mocks = vi.hoisted(() => ({
  workspace: {
    activeWorkspaceId: "workspace-1",
    activeWorkspace: { id: "workspace-1", name: "Context Engine" },
    workspacesQuery: { isLoading: false },
    workspaces: [{ id: "workspace-1", name: "Context Engine" }],
    selectedId: "workspace-1",
    setSelectedId: vi.fn(),
  },
}));

vi.mock("../api/client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../components/WorkspaceTopicGate", () => ({
  default: () => <div>Choose a workspace</div>,
}));

describe("SourceManager", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    mocks.workspace.activeWorkspaceId = "workspace-1";
    mocks.workspace.activeWorkspace = { id: "workspace-1", name: "Context Engine" };
    mocks.workspace.workspacesQuery = { isLoading: false };
    mocks.workspace.workspaces = [{ id: "workspace-1", name: "Context Engine" }];
    mocks.workspace.selectedId = "workspace-1";
    mocks.workspace.setSelectedId.mockReset();
  });

  it("loads source list and details inside the active workspace boundary", async () => {
    api.get.mockImplementation(async (path) => {
      if (path === "/source-documents?workspace_id=workspace-1&limit=100") {
        return {
          items: [
            {
              id: "source-1",
              source_type: "slack",
              external_id: "slack:C123:1",
              author: "Asha",
              content_preview: "Decision: keep the inspector source-backed.",
              processed_at: "2026-06-18T00:00:00Z",
            },
          ],
          has_more: false,
          next_cursor: null,
        };
      }
      if (path === "/sources/source-1?workspace_id=workspace-1") {
        return {
          id: "source-1",
          content: "Decision: keep the inspector source-backed.",
          components: [
            {
              id: "component-1",
              name: "Inspector provenance decision",
              value: "Keep the inspector source-backed.",
              confidence: 0.92,
            },
          ],
        };
      }
      throw new Error(`Unexpected API path: ${path}`);
    });

    render(<SourceManager />);

    expect(await screen.findByText("Slack")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /slack/i }));
    fireEvent.click(await screen.findByText("slack:C123:1"));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        "/sources/source-1?workspace_id=workspace-1",
      );
    });
    expect(await screen.findByText("Keep the inspector source-backed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close source details" })).toBeInTheDocument();
  });

  it("separates unsupported provider records from supported documents", async () => {
    api.get.mockImplementation(async (path) => {
      if (path === "/source-documents?workspace_id=workspace-1&limit=100") {
        return {
          items: [
            {
              id: "local-1",
              source_type: "browser_upload",
              external_id: "roadmap.md",
              content_preview: "Launch checklist",
              processed_at: "2026-06-18T00:00:00Z",
            },
            {
              id: "notion-1",
              source_type: "notion",
              external_id: "notion:roadmap",
              content_preview: "Legacy import",
              processed_at: "2026-06-18T00:00:00Z",
            },
            {
              id: "zoom-1",
              source_type: "zoom_transcript",
              external_id: "zoom:standup",
              content_preview: "Legacy transcript",
              processed_at: "2026-06-18T00:00:00Z",
            },
          ],
          has_more: false,
          next_cursor: null,
        };
      }
      throw new Error(`Unexpected API path: ${path}`);
    });

    render(<SourceManager />);

    const documentsButton = (await screen.findByText("Documents")).closest("button");
    const unsupportedButton = screen.getByText("Unsupported").closest("button");
    expect(documentsButton).toHaveTextContent("1");
    expect(unsupportedButton).toHaveTextContent("2");

    fireEvent.click(unsupportedButton);

    expect(await screen.findByText("notion:roadmap")).toBeInTheDocument();
    expect(screen.getByText("zoom:standup")).toBeInTheDocument();
  });

  it("uploads browser files into the active workspace", async () => {
    api.get.mockResolvedValue({
      items: [],
      has_more: false,
      next_cursor: null,
    });
    api.post.mockResolvedValue({});

    render(<SourceManager />);

    expect(await screen.findByText("No sources yet")).toBeInTheDocument();

    const input = document.querySelector('input[type="file"]');
    fireEvent.change(input, {
      target: {
        files: [
          new File(["# Launch"], "launch.md", { type: "text/markdown" }),
          new File(["plain notes"], "notes.unknown", { type: "text/plain" }),
        ],
      },
    });

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledTimes(2);
    });

    expect(api.post).toHaveBeenNthCalledWith(1, "/sources", expect.objectContaining({
      workspace_id: "workspace-1",
      source_type: "markdown",
      external_id: "launch.md",
      metadata: expect.objectContaining({ workspace_id: "workspace-1" }),
    }));
    expect(api.post).toHaveBeenNthCalledWith(2, "/sources", expect.objectContaining({
      workspace_id: "workspace-1",
      source_type: "text",
      external_id: "notes.unknown",
      metadata: expect.objectContaining({ workspace_id: "workspace-1" }),
    }));
    expect(api.post).not.toHaveBeenCalledWith(
      "/sources",
      expect.objectContaining({ source_type: expect.stringMatching(/notion|zoom/i) }),
    );
  });

  it("exposes the upload dropzone as a keyboard-operable button", async () => {
    api.get.mockResolvedValue({
      items: [],
      has_more: false,
      next_cursor: null,
    });

    render(<SourceManager />);

    expect(await screen.findByText("No sources yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import files" }));

    const dropzone = screen.getByRole("button", { name: /Drop files here or browse/i });
    expect(dropzone).toHaveAttribute("aria-describedby", "source-import-formats");
    expect(dropzone).toHaveAttribute("type", "button");
  });

  it("clears selected source state and refetches only within the new workspace", async () => {
    api.get.mockImplementation(async (path) => {
      if (path === "/source-documents?workspace_id=workspace-1&limit=100") {
        return {
          items: [{
            id: "source-1",
            source_type: "browser_upload",
            external_id: "workspace-one.md",
            processed_at: "2026-06-18T00:00:00Z",
          }],
          has_more: false,
          next_cursor: null,
        };
      }
      if (path === "/sources/source-1?workspace_id=workspace-1") {
        return {
          id: "source-1",
          content: "Workspace one detail",
          components: [],
        };
      }
      if (path === "/source-documents?workspace_id=workspace-2&limit=100") {
        return {
          items: [{
            id: "source-2",
            source_type: "browser_upload",
            external_id: "workspace-two.md",
            processed_at: "2026-06-18T00:00:00Z",
          }],
          has_more: false,
          next_cursor: null,
        };
      }
      throw new Error(`Unexpected API path: ${path}`);
    });

    const { rerender } = render(<SourceManager />);
    fireEvent.click((await screen.findByText("Documents")).closest("button"));
    fireEvent.click(await screen.findByText("workspace-one.md"));
    expect(await screen.findByText("Workspace one detail")).toBeInTheDocument();

    mocks.workspace.activeWorkspaceId = "workspace-2";
    mocks.workspace.activeWorkspace = { id: "workspace-2", name: "Second project" };
    mocks.workspace.workspaces = [
      { id: "workspace-1", name: "Context Engine" },
      { id: "workspace-2", name: "Second project" },
    ];
    mocks.workspace.selectedId = "workspace-2";
    rerender(<SourceManager />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        "/source-documents?workspace_id=workspace-2&limit=100",
      );
    });
    expect(screen.queryByRole("button", { name: "Close source details" })).not.toBeInTheDocument();

    fireEvent.click((await screen.findByText("Documents")).closest("button"));
    expect(await screen.findByText("workspace-two.md")).toBeInTheDocument();
    expect(screen.queryByText("workspace-one.md")).not.toBeInTheDocument();
    expect(api.get.mock.calls.every(([path]) => path.includes("workspace_id="))).toBe(true);
  });

  it("does not fall back to an unscoped source request", async () => {
    mocks.workspace.activeWorkspaceId = null;
    mocks.workspace.activeWorkspace = null;
    mocks.workspace.workspaces = [];
    mocks.workspace.selectedId = null;

    render(<SourceManager />);

    expect(await screen.findByText("Choose a workspace")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });
});
