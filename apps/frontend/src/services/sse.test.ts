import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

describe("SseParser", () => {
  it("parses whole events", () => {
    const parser = new SseParser();

    expect(parser.push('event: delta\ndata: {"a":1}\nid: 3\n\n')).toEqual([
      { event: "delta", data: '{"a":1}', id: "3" },
    ]);
  });

  it("reassembles events split across arbitrary chunk boundaries", () => {
    const parser = new SseParser();
    const text = "event: delta\ndata: hello\n\nevent: completed\ndata: {}\n\n";

    const messages = [...text].flatMap((char) => parser.push(char));

    expect(messages.map((m) => [m.event, m.data])).toEqual([
      ["delta", "hello"],
      ["completed", "{}"],
    ]);
  });

  it("supports CRLF line endings, including a CRLF split between chunks", () => {
    const parser = new SseParser();

    const messages = [
      ...parser.push("event: delta\r"),
      ...parser.push("\ndata: x\r\n\r"),
      ...parser.push("\n"),
    ];

    expect(messages).toEqual([{ event: "delta", data: "x", id: null }]);
  });

  it("joins multi-line data and ignores comments", () => {
    const parser = new SseParser();

    expect(parser.push(": keep-alive\n\ndata: a\ndata: b\n\n")).toEqual([
      { event: "message", data: "a\nb", id: null },
    ]);
  });

  it("does not emit a partial event", () => {
    const parser = new SseParser();

    expect(parser.push("event: delta\ndata: incomplete")).toEqual([]);
  });
});
