import { describe, expect, it } from "vitest";

import { ApiError } from "./client";


describe("ApiError", () => {
  it("uses a structured API message instead of raw JSON", () => {
    const error = new ApiError(422, {
      code: "focus_not_eligible",
      message: "Pull requests are delivery evidence.",
    });

    expect(error.message).toBe("Pull requests are delivery evidence.");
    expect(error.message).not.toContain("focus_not_eligible");
    expect(error.status).toBe(422);
  });
});
