import { describe, expect, it } from "vitest";
import type { ServerEvent } from "@doc-pipeline/shared-types";
import { ApiError, listKnowledgeBases, streamChat } from "./chatApi";

const request = { sessionId: "s", knowledgeBaseId: "ABCDE12345", prompt: "hi" };

function sse(name: string, body: Record<string, unknown>, sequence: number): string {
  const data = JSON.stringify({ requestId: "r", sequence, type: name, ...body });
  return `event: ${name}\ndata: ${data}\nid: ${sequence}\n\n`;
}

function streamingResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

describe("streamChat", () => {
  it("emits validated events in order, even when the network splits them mid-event", async () => {
    const text =
      sse("route", { route: "easy" }, 0) + sse("delta", { text: "Hi" }, 1) + sse("completed", {}, 2);
    const cut = Math.floor(text.length / 3);
    const seen: ServerEvent[] = [];

    await streamChat(
      request,
      (event) => seen.push(event),
      undefined,
      async () => streamingResponse([text.slice(0, cut), text.slice(cut, cut * 2), text.slice(cut * 2)]),
    );

    expect(seen.map((e) => e.type)).toEqual(["route", "delta", "completed"]);
  });

  it("delivers each event before the stream ends", async () => {
    const encoder = new TextEncoder();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const body = new ReadableStream<Uint8Array>({
      async start(controller) {
        controller.enqueue(encoder.encode(sse("delta", { text: "first" }, 0)));
        await gate;
        controller.enqueue(encoder.encode(sse("completed", {}, 1)));
        controller.close();
      },
    });
    const seen: string[] = [];
    let firstSeen!: () => void;
    const first = new Promise<void>((resolve) => (firstSeen = resolve));

    const done = streamChat(
      request,
      (event) => {
        seen.push(event.type);
        if (event.type === "delta") firstSeen();
      },
      undefined,
      async () => new Response(body, { status: 200 }),
    );

    await first;
    expect(seen).toEqual(["delta"]); // observed while the server is still streaming
    release();
    await done;
    expect(seen).toEqual(["delta", "completed"]);
  });

  it("skips malformed and unknown events without failing the stream", async () => {
    const seen: string[] = [];

    await streamChat(
      request,
      (event) => seen.push(event.type),
      undefined,
      async () =>
        streamingResponse([
          "event: delta\ndata: not-json\n\n",
          'event: ping\ndata: {"type":"ping"}\n\n',
          sse("completed", {}, 0),
        ]),
    );

    expect(seen).toEqual(["completed"]);
  });

  it("posts the request as JSON and throws ApiError on a non-2xx status", async () => {
    let captured: RequestInit | undefined;

    await expect(
      streamChat(request, () => {}, undefined, async (_url, init) => {
        captured = init;
        return new Response("nope", { status: 404 });
      }),
    ).rejects.toMatchObject({ status: 404 });

    expect(captured?.method).toBe("POST");
    expect(JSON.parse(String(captured?.body))).toEqual(request);
    await expect(
      streamChat(request, () => {}, undefined, async () => new Response("x", { status: 500 })),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("listKnowledgeBases", () => {
  it("returns validated knowledge bases", async () => {
    const list = await listKnowledgeBases(
      async () =>
        new Response(
          JSON.stringify({ knowledgeBases: [{ id: "ABCDE12345", name: "Manual", status: "READY" }] }),
        ),
    );

    expect(list).toEqual([
      { id: "ABCDE12345", name: "Manual", status: "READY", pages: null, updatedAt: null },
    ]);
  });

  it("throws ApiError when the request fails", async () => {
    await expect(listKnowledgeBases(async () => new Response("", { status: 502 }))).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});
