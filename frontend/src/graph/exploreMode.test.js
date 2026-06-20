import { describe, expect, it } from "vitest";
import {
  buildExploreNeighborhood,
  connectedComponentIds,
  filterExploreComponents,
} from "./exploreMode";

const components = [
  { id: "a", name: "A" },
  { id: "b", name: "B" },
  { id: "c", name: "C" },
  { id: "orphan", name: "Orphan" },
];

const relationships = [
  { source_component_id: "a", target_component_id: "b", relationship_type: "depends_on", confidence: 0.8 },
  { source_component_id: "b", target_component_id: "c", relationship_type: "blocks", confidence: 0.7 },
];

describe("connectedComponentIds", () => {
  it("collects ids from both relationship endpoints", () => {
    expect([...connectedComponentIds(relationships)].sort()).toEqual(["a", "b", "c"]);
  });
});

describe("filterExploreComponents", () => {
  it("hides orphan components by default", () => {
    expect(filterExploreComponents(components, relationships).map((component) => component.id)).toEqual(["a", "b", "c"]);
  });
});

describe("buildExploreNeighborhood", () => {
  it("returns 1-hop neighbors by default", () => {
    expect(buildExploreNeighborhood("a", components, relationships, 1).map((component) => component.id)).toEqual(["b"]);
  });

  it("returns 2-hop neighbors when requested", () => {
    expect(buildExploreNeighborhood("a", components, relationships, 2).map((component) => component.id)).toEqual(["b", "c"]);
  });
});
