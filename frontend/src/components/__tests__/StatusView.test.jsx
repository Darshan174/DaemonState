import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import StatusView from "../StatusView";

describe("StatusView", () => {
  it("shows loading spinner", () => {
    render(
      <MemoryRouter>
        <StatusView query={{ isLoading: true, isError: false }} />
      </MemoryRouter>
    );

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows error with message and retry button", async () => {
    const refetch = vi.fn();
    render(
      <MemoryRouter>
        <StatusView
          query={{
            isLoading: false,
            isError: true,
            error: { message: "Connection refused" },
            refetch,
          }}
        />
      </MemoryRouter>
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Failed to load data")).toBeInTheDocument();
    expect(screen.getByText("Connection refused")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows default error message when error.message is absent", () => {
    render(
      <MemoryRouter>
        <StatusView
          query={{ isLoading: false, isError: true, error: {}, refetch: vi.fn() }}
        />
      </MemoryRouter>
    );

    expect(screen.getByText("Something went wrong.")).toBeInTheDocument();
  });

  it("shows empty state for null data", () => {
    render(
      <MemoryRouter>
        <StatusView
          query={{ isLoading: false, isError: false, data: null }}
          empty="Nothing here."
        />
      </MemoryRouter>
    );

    expect(screen.getByText("Nothing here.")).toBeInTheDocument();
  });

  it("shows empty state for empty array", () => {
    render(
      <MemoryRouter>
        <StatusView
          query={{ isLoading: false, isError: false, data: [] }}
          empty="No items."
        />
      </MemoryRouter>
    );

    expect(screen.getByText("No items.")).toBeInTheDocument();
  });

  it("shows empty state for empty object", () => {
    render(
      <MemoryRouter>
        <StatusView
          query={{ isLoading: false, isError: false, data: {} }}
        />
      </MemoryRouter>
    );

    expect(screen.getByText("Nothing here yet.")).toBeInTheDocument();
  });

  it("returns null when data is present", () => {
    const { container } = render(
      <MemoryRouter>
        <StatusView
          query={{ isLoading: false, isError: false, data: [{ id: 1 }] }}
        />
      </MemoryRouter>
    );

    expect(container.innerHTML).toBe("");
  });
});
