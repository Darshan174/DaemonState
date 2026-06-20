import { describe, expect, it } from "vitest";
import {
  boardGraphGroup,
  passesBoardLens,
  filterGapsLens,
  resolveRelationshipEdgeStyle,
  boardReadablePan,
  shouldUseReadableBoardViewport,
  BOARD_READABLE_ZOOM,
} from "./boardMode";

function kind(component) {
  if (component.source_type?.includes("github")) return "github";
  if (component.source_type?.includes("slack")) return "slack";
  return "other";
}

function family(component) {
  if (component.source_type?.includes("github")) return "github";
  if (component.source_type?.includes("slack")) return "communication";
  return "other";
}

describe("boardGraphGroup", () => {
  it("groups by source kind in board mode", () => {
    expect(boardGraphGroup({ source_type: "github_issue" }, kind, family)).toBe("github");
    expect(boardGraphGroup({ source_type: "slack_message" }, kind, family)).toBe("slack");
  });
});

describe("passesBoardLens", () => {
  it("filters work items", () => {
    expect(passesBoardLens({ fact_type: "github_issue" }, "Tasks", "work")).toBe(true);
    expect(passesBoardLens({ fact_type: "decision" }, "Decisions", "work")).toBe(false);
  });
});

describe("filterGapsLens", () => {
  it("keeps only isolated components", () => {
    const components = [{ id: "a" }, { id: "b" }];
    const relationships = [{ source_component_id: "a", target_component_id: "b" }];
    expect(filterGapsLens(components, relationships)).toEqual([]);
  });
});

describe("readable board viewport", () => {
  it("uses a readable card viewport when full fit would collapse Board into dots", () => {
    expect(BOARD_READABLE_ZOOM).toBeGreaterThan(0.7);
    expect(shouldUseReadableBoardViewport({
      viewMode: "knowledge",
      graphLayout: "board",
      fitZoom: 0.38,
    })).toBe(true);
  });

  it("keeps normal fit behavior outside Board", () => {
    expect(shouldUseReadableBoardViewport({
      viewMode: "knowledge",
      graphLayout: "explore",
      fitZoom: 0.38,
    })).toBe(false);
    expect(shouldUseReadableBoardViewport({
      viewMode: "repo",
      graphLayout: "board",
      fitZoom: 0.38,
    })).toBe(false);
  });

  it("pans the top-left graph bounds into the readable viewport", () => {
    const pan = boardReadablePan({ x1: -120, y1: 40 }, 0.82);
    expect(pan.x).toBeCloseTo(126.4);
    expect(pan.y).toBeCloseTo(53.2);
  });
});

describe("resolveRelationshipEdgeStyle", () => {
  it("uses quiet edges by default", () => {
    const style = resolveRelationshipEdgeStyle({
      relationship: { origin: "ai_proposed" },
      sameGroup: false,
      showTrustEdges: false,
      isDark: true,
    });
    expect(style.lineStyle).toBe("solid");
    expect(style.color).toBe("#60a5fa");
  });

  it("preserves origin styling when trust mode is on", () => {
    const style = resolveRelationshipEdgeStyle({
      relationship: { origin: "ai_proposed" },
      sameGroup: false,
      showTrustEdges: true,
      isDark: true,
    });
    expect(style.lineStyle).toBe("dashed");
  });
});
