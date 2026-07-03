import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import DigestBoard from "./DigestBoard";

function digestCard(overrides) {
  return {
    id: overrides.id,
    title: overrides.title,
    summary: overrides.summary,
    type: overrides.type,
    status: overrides.status || "active",
    attention_score: overrides.attention_score ?? 50,
    provenance: overrides.provenance || [],
    ...overrides,
  };
}

const digest = {
  generated_at: "2026-07-02T12:00:00Z",
  health: { status: "healthy" },
  cards: [
    digestCard({
      id: "session-1",
      type: "agent_session",
      title: "Agent session: restore graph board",
      summary: "Codex restored the graph board layout and connector overlay.",
      attention_score: 90,
    }),
    digestCard({
      id: "decision-1",
      type: "decision",
      title: "Decision: keep the digest board",
      summary: "Keep the digest board as the default graph route.",
      attention_score: 80,
    }),
    digestCard({
      id: "pr-1",
      type: "source",
      title: "PR #12",
      summary: "PR 12 fixes graph review regressions.",
      attention_score: 70,
      provenance: [{ source_url: "https://github.com/example/context-engine/pull/12" }],
    }),
  ],
};

describe("DigestBoard", () => {
  it("renders connector lines without white glow underlays", () => {
    const { container } = render(
      <MemoryRouter>
        <DigestBoard digest={digest} workspaceName="Test workspace" generatedAt={digest.generated_at} />
      </MemoryRouter>,
    );

    const connectorGroups = container.querySelectorAll("[data-component-line]");
    expect(connectorGroups.length).toBeGreaterThan(0);
    expect(container.querySelector("#component-line-glow")).toBeNull();
    expect(container.querySelector('[filter="url(#component-line-glow)"]')).toBeNull();

    connectorGroups.forEach((group) => {
      const paths = group.querySelectorAll("path");
      expect(paths).toHaveLength(1);
      expect(paths[0]).toHaveAttribute("stroke", "rgba(37,99,235,0.42)");
      expect(paths[0]).not.toHaveAttribute("stroke", "rgba(255,255,255,0.72)");
    });
  });
});
