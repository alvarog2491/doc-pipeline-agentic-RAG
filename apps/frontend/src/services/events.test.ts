import { describe, expect, it } from "vitest";
import { parseKnowledgeBaseList, parseServerEvent } from "@doc-pipeline/shared-types";

const base = { requestId: "r1", sequence: 0 };

describe("parseServerEvent", () => {
  it("accepts every well-formed event type", () => {
    const cases: [string, Record<string, unknown>][] = [
      ["route", { route: "guide" }],
      ["progress", { text: "Searching…" }],
      ["delta", { text: "hi" }],
      ["citations", { citations: [{ id: 1, page: 2, section: "", url: null }] }],
      ["completed", {}],
      ["error", { code: "agent_unavailable", message: "try again" }],
    ];
    for (const [type, extra] of cases) {
      expect(parseServerEvent(type, { ...base, type, ...extra }).type).toBe(type);
    }
  });

  it.each([
    ["type does not match the SSE event name", "delta", { ...base, type: "progress", text: "x" }],
    ["unknown route", "route", { ...base, type: "route", route: "medium" }],
    ["delta without text", "delta", { ...base, type: "delta" }],
    ["negative sequence", "delta", { ...base, sequence: -1, type: "delta", text: "x" }],
    ["fractional sequence", "delta", { ...base, sequence: 1.5, type: "delta", text: "x" }],
    ["missing requestId", "completed", { sequence: 0, type: "completed" }],
    ["malformed citation", "citations", { ...base, type: "citations", citations: [{ id: "1" }] }],
    ["unknown error code", "error", { ...base, type: "error", code: "boom", message: "m" }],
    ["unknown event", "ping", { ...base, type: "ping" }],
    ["non-object data", "delta", "text"],
  ])("rejects %s", (_label, name, data) => {
    expect(() => parseServerEvent(name, data)).toThrow("Unsupported server event");
  });
});

describe("parseKnowledgeBaseList", () => {
  it("normalises optional fields", () => {
    const list = parseKnowledgeBaseList({
      knowledgeBases: [
        { id: "ABCDE12345", name: "Manual", status: "READY", pages: 12, updatedAt: "2026-01-01" },
        { id: "b-1", name: "New", status: "PROCESSING" },
        { id: "b-2", name: "Big", status: "INDEXING" },
      ],
    });

    expect(list[0].pages).toBe(12);
    expect(list[1]).toMatchObject({ pages: null, updatedAt: null });
    expect(list[2].status).toBe("INDEXING");
  });

  it("rejects malformed lists", () => {
    expect(() => parseKnowledgeBaseList({})).toThrow();
    expect(() =>
      parseKnowledgeBaseList({ knowledgeBases: [{ id: "x", name: "y", status: "DONE" }] }),
    ).toThrow();
  });
});
