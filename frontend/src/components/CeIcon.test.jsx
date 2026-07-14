import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CeIcon from "./CeIcon";

describe("CeIcon", () => {
  it.each([24, 30, 34])("renders the circular node-path mark at %d px", (size) => {
    const { container } = render(<CeIcon size={size} className="brand-mark" />);
    const svg = container.querySelector("svg");

    expect(svg).toHaveAttribute("width", String(size));
    expect(svg).toHaveAttribute("height", String(size));
    expect(svg).toHaveAttribute("viewBox", "0 0 40 40");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("focusable", "false");
    expect(svg).toHaveClass("brand-mark");

    expect(svg.querySelector('circle[fill="#fff"][stroke="#000"]')).toBeInTheDocument();
    expect(svg.querySelectorAll('circle[fill="#000"]')).toHaveLength(4);
    expect(svg.querySelectorAll('circle[fill="#ef1019"]')).toHaveLength(1);

    const path = svg.querySelector("polyline");
    expect(path).toHaveAttribute(
      "points",
      "13.2 11, 7.5 20.9, 16.2 26.7, 21.1 11, 26.7 25.9, 31.5 10.6",
    );
    expect(path).toHaveAttribute("fill", "none");
    expect(svg.querySelector('circle[cx="31.5"][cy="10.6"]')).not.toBeInTheDocument();
  });

  it("keeps the browser favicon aligned with the shared component", () => {
    const { container } = render(<CeIcon />);
    const component = container.querySelector("svg");
    const faviconMarkup = readFileSync(resolve(process.cwd(), "public/favicon.svg"), "utf8");
    const favicon = new DOMParser().parseFromString(faviconMarkup, "image/svg+xml").documentElement;
    const attributes = [
      "cx",
      "cy",
      "r",
      "fill",
      "stroke",
      "stroke-width",
      "points",
      "stroke-linecap",
      "stroke-linejoin",
    ];
    const nodeSignature = (node) => attributes.map((attribute) => node.getAttribute(attribute));
    const signature = (root) => ({
      circles: [...root.querySelectorAll("circle")].map(nodeSignature),
      polyline: nodeSignature(root.querySelector("polyline")),
    });

    expect(favicon.getAttribute("viewBox")).toBe(component.getAttribute("viewBox"));
    expect(signature(favicon)).toEqual(signature(component));
  });
});
