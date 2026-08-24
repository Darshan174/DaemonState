import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import PermissionsTerms from "./PermissionsTerms";


describe("PermissionsTerms", () => {
  it("matches the current shipped SUL grant and separately licensed offerings", () => {
    render(
      <MemoryRouter>
        <PermissionsTerms />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Permissions & terms" }))
      .toBeInTheDocument();
    expect(screen.getByText(/plain-language guide/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Read current license/i }))
      .toHaveAttribute("href", "/assets/legal/LICENSE");
    expect(screen.getByRole("link", { name: /View public toolkit/i }))
      .toHaveAttribute("href", "https://github.com/Darshan174/DaemonState");

    expect(screen.getByText(/packaged product built from this repository/i))
      .toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "The terms follow what you receive" }))
      .toBeInTheDocument();
    expect(screen.getByText(/current packaged DaemonState product/i))
      .toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What SUL-1.0 permits" }))
      .toBeInTheDocument();
    expect(screen.getByText(/including the current packaged product and public toolkit/i))
      .toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Commercial uses need permission" }))
      .toBeInTheDocument();
    expect(screen.getByText(/grants are not retroactively revoked/i))
      .toBeInTheDocument();
    expect(screen.queryByText(/DaemonState 0\.3\.0 and later/i))
      .not.toBeInTheDocument();
    expect(screen.queryByText(/Only the public integration and demonstration toolkit/i))
      .not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "privacy notice" }))
      .toHaveAttribute("href", "/privacy");
  });
});
