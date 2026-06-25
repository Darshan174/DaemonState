import { describe, expect, it } from "vitest";
import {
  githubSourceUrl,
  isDeterministicMentionEdge,
  sourceDocumentPath,
} from "./inspectorUtils";

describe("inspectorUtils", () => {
  it("builds github issue url from repo metadata", () => {
    expect(githubSourceUrl({
      source_type: "github",
      source_metadata_summary: { repo: "acme/app", number: 42 },
      fact_type: "issue",
    })).toBe("https://github.com/acme/app/issues/42");
  });

  it("prefers explicit source_url", () => {
    expect(githubSourceUrl({
      source_url: "https://github.com/acme/app/pull/7",
      source_metadata_summary: { repo: "acme/app", number: 42 },
    })).toBe("https://github.com/acme/app/pull/7");
  });

  it("builds source document path", () => {
    expect(sourceDocumentPath("doc-123")).toBe("/app/sources?source_id=doc-123");
    expect(sourceDocumentPath(null)).toBeNull();
  });

  it("detects deterministic mention edges", () => {
    expect(isDeterministicMentionEdge({ origin: "deterministic", label: "mentions" })).toBe(true);
    expect(isDeterministicMentionEdge({ origin: "ai_proposed", label: "mentions" })).toBe(false);
  });
});
