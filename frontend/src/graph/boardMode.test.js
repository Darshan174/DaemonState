import { describe, expect, it } from "vitest";
import {
  boardGraphGroup,
  passesBoardLens,
  filterGapsLens,
  resolveRelationshipEdgeStyle,
  boardReadablePan,
  shouldUseReadableBoardViewport,
  BOARD_READABLE_ZOOM,
  boardModelGroupKey,
  boardModelColor,
  boardShardGeometry,
  buildBoardShardClusterLayout,
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

describe("board model groups", () => {
  it("creates stable model group keys", () => {
    expect(boardModelGroupKey("model-1")).toBe("model:model-1");
    expect(boardModelGroupKey()).toBe("model:unmodeled");
  });

  it("assigns deterministic model colors", () => {
    expect(boardModelColor("Project")).toBe(boardModelColor("Project"));
    expect(boardModelColor("Project")).toMatch(/^#[0-9a-f]{6}$/);
  });
});

describe("buildBoardShardClusterLayout", () => {
  it("places components on a circular shard ring by default", () => {
    const layout = buildBoardShardClusterLayout(10);
    expect(layout.positions).toHaveLength(10);
    expect(layout.width).toBeGreaterThan(320);
    expect(layout.height).toBeGreaterThan(260);

    expect(layout.positions.some((pos) => pos.x < 0)).toBe(true);
    expect(layout.positions.some((pos) => pos.x > 0)).toBe(true);
    expect(layout.positions.some((pos) => pos.y < 0)).toBe(true);
    expect(layout.positions.some((pos) => pos.y > 0)).toBe(true);
  });

  it("adds inner rings for dense models while staying compact", () => {
    const layout = buildBoardShardClusterLayout(32);
    expect(layout.positions).toHaveLength(32);
    expect(new Set(layout.positions.map((pos) => pos.ring)).size).toBeGreaterThan(1);
    expect(layout.width / layout.height).toBeLessThan(3);
  });
});

describe("boardShardGeometry", () => {
  it("returns deterministic irregular polygon metadata", () => {
    const shard = boardShardGeometry("component-1", 3, { angle: 42, scale: 0.75 });
    expect(shard.width).toBeGreaterThan(40);
    expect(shard.height).toBeGreaterThan(30);
    expect(shard.polygonPoints.split(" ")).toHaveLength(10);
    expect(shard.clipPath).toMatch(/^polygon\(/);
    expect(shard.svgPoints.split(" ")).toHaveLength(5);
    expect(boardShardGeometry("component-1", 3, { angle: 42, scale: 0.75 })).toEqual(shard);
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
  it("keeps the readable fallback below the compact board fit target", () => {
    expect(BOARD_READABLE_ZOOM).toBeGreaterThan(0.5);
    expect(BOARD_READABLE_ZOOM).toBeLessThan(0.7);
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
    expect(pan.x).toBeCloseTo(122.4);
    expect(pan.y).toBeCloseTo(39.2);
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
