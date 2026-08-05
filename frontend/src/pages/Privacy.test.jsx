import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import Privacy from "./Privacy";


describe("Privacy", () => {
  it("explains the waitlist data flow and provides a private contact path", () => {
    render(
      <MemoryRouter>
        <Privacy />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Privacy notice" })).toBeInTheDocument();
    expect(screen.getByText(/Cloudflare hosts the public site and D1 waitlist database/i))
      .toBeInTheDocument();
    expect(screen.getByText(/does not send your email address/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Contact the repository owner" }))
      .toHaveAttribute("href", "https://github.com/Darshan174");
    expect(screen.getByRole("link", { name: "Return to early access" }))
      .toHaveAttribute("href", "/#early-access");
    expect(screen.getByRole("link", { name: "Permissions & terms" }))
      .toHaveAttribute("href", "/permissions-terms");
  });
});
