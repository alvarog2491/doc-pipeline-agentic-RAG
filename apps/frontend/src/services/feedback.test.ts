import { describe, expect, it, vi } from "vitest";
import { buildFeedbackBody, submitFeedback } from "./feedback";

describe("buildFeedbackBody", () => {
  it("keeps a trimmed comment for a not_helpful outcome", () => {
    expect(
      buildFeedbackBody({ sessionId: "s1", outcome: "not_helpful", comment: "  no citations  " }),
    ).toEqual({ sessionId: "s1", outcome: "not_helpful", comment: "no citations" });
  });

  it("omits the comment when it is missing or blank", () => {
    expect(buildFeedbackBody({ sessionId: "s1", outcome: "helpful" })).toEqual({
      sessionId: "s1",
      outcome: "helpful",
    });
    expect(
      buildFeedbackBody({ sessionId: "s1", outcome: "helpful", comment: "   " }),
    ).toEqual({ sessionId: "s1", outcome: "helpful" });
  });
});

describe("submitFeedback", () => {
  it("POSTs JSON to /v1/feedback", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: true, status: 200 });

    await submitFeedback(
      { sessionId: "s1", outcome: "helpful" },
      fetchImpl as unknown as typeof fetch,
    );

    expect(fetchImpl).toHaveBeenCalledWith("/v1/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: "s1", outcome: "helpful" }),
    });
  });

  it("throws when the server rejects the request", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 502 });

    await expect(
      submitFeedback(
        { sessionId: "s1", outcome: "not_helpful", comment: "broken" },
        fetchImpl as unknown as typeof fetch,
      ),
    ).rejects.toThrow("status 502");
  });
});
