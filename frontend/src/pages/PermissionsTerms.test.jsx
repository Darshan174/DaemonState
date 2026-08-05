import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import PermissionsTerms from "./PermissionsTerms";


describe("PermissionsTerms", () => {
  it("summarizes the controlling GitHub license without expanding its grant", () => {
    render(
      <MemoryRouter>
        <PermissionsTerms />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Permissions & terms" }))
      .toBeInTheDocument();
    expect(screen.getByText(/plain-language guide/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Read the license" }))
      .toHaveAttribute("href", "/assets/legal/LICENSE");
    expect(screen.getByRole("link", { name: /GitHub guide/i }))
      .toHaveAttribute(
        "href",
        "https://github.com/Darshan174/DaemonState/blob/main/docs/licensing.md",
      );

    expect(screen.getByRole("heading", { name: "What you may do" }))
      .toBeInTheDocument();
    expect(screen.getByText(/own self-hosted installation/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Commercial uses need permission" }))
      .toBeInTheDocument();
    expect(screen.getByText(/paid hosted or managed service/i)).toBeInTheDocument();
    expect(screen.getByText(/Versions through 0.2.0 were released under the MIT License/i))
      .toBeInTheDocument();
    expect(screen.getByRole("link", { name: "privacy notice" }))
      .toHaveAttribute("href", "/privacy");
  });
});
