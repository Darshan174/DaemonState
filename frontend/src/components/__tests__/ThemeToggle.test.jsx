import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ThemeToggle from "../ThemeToggle";
import { ThemeProvider } from "../../context/ThemeContext";

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  document.documentElement.style.colorScheme = "";
});

describe("ThemeToggle", () => {
  it("toggles between light and dark mode", async () => {
    renderToggle();

    const toggle = screen.getByRole("button", { name: /switch to dark mode/i });
    expect(document.documentElement).not.toHaveClass("dark");

    await userEvent.click(toggle);
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("ce-theme")).toBe("dark");

    await userEvent.click(screen.getByRole("button", { name: /switch to light mode/i }));
    expect(document.documentElement).not.toHaveClass("dark");
    expect(localStorage.getItem("ce-theme")).toBe("light");
  });

  it("uses the current document theme when toggling", async () => {
    renderToggle();
    document.documentElement.classList.add("dark");

    await userEvent.click(screen.getByRole("button", { name: /switch to dark mode/i }));

    expect(document.documentElement).not.toHaveClass("dark");
    expect(localStorage.getItem("ce-theme")).toBe("light");
  });
});
