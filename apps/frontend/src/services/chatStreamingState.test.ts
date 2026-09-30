import { describe, expect, it } from "vitest";
import { shouldShowThinkingIndicator } from "./chatStreamingState";

describe("shouldShowThinkingIndicator", () => {
  it("shows the thinking indicator for the full streaming period", () => {
    expect(shouldShowThinkingIndicator(true)).toBe(true);
  });

  it("hides the thinking indicator when processing is complete", () => {
    expect(shouldShowThinkingIndicator(false)).toBe(false);
  });
});
