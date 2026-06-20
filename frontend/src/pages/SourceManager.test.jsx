import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SourceManager from "./SourceManager";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

describe("SourceManager", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
  });

  it("loads source list and details through the shared API client", async () => {
    api.get.mockImplementation(async (path) => {
      if (path === "/source-documents?limit=100") {
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
      if (path === "/sources/source-1") {
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
      expect(api.get).toHaveBeenCalledWith("/sources/source-1");
    });
    expect(await screen.findByText("Keep the inspector source-backed.")).toBeInTheDocument();
  });

  it("separates unsupported provider records from supported documents", async () => {
    api.get.mockImplementation(async (path) => {
      if (path === "/source-documents?limit=100") {
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

  it("uploads browser files as local document source types", async () => {
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
      source_type: "markdown",
      external_id: "launch.md",
    }));
    expect(api.post).toHaveBeenNthCalledWith(2, "/sources", expect.objectContaining({
      source_type: "text",
      external_id: "notes.unknown",
    }));
    expect(api.post).not.toHaveBeenCalledWith(
      "/sources",
      expect.objectContaining({ source_type: expect.stringMatching(/notion|zoom/i) }),
    );
  });
});
