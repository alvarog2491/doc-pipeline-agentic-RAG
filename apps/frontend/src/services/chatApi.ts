import {
  parseKnowledgeBaseList,
  parseServerEvent,
  type ChatRequest,
  type KnowledgeBase,
  type ServerEvent,
} from "@doc-pipeline/shared-types";
import { SseParser } from "./sse";

/** Base URL of the API; empty means same-origin (the Vite/nginx proxy). */
export function apiBase(): string {
  return (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/**
 * Streams one chat turn, calling `onEvent` for every validated event the moment it arrives.
 *
 * Uses `fetch` with a readable stream because `EventSource` cannot POST a body.
 *
 * @param request Chat request body.
 * @param onEvent Called once per server event, in order.
 * @param signal Aborts the stream when the user leaves the conversation.
 * @param fetchImpl Injected for tests.
 * @throws ApiError when the server rejects the request before streaming starts.
 */
export async function streamChat(
  request: ChatRequest,
  onEvent: (event: ServerEvent) => void,
  signal?: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const response = await fetchImpl(`${apiBase()}/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new ApiError(`Chat request failed with status ${response.status}`, response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const message of parser.push(decoder.decode(value, { stream: true }))) {
      let event: ServerEvent;
      try {
        event = parseServerEvent(message.event, JSON.parse(message.data));
      } catch {
        continue; // an unknown or malformed event must not break the stream
      }
      onEvent(event);
    }
  }
}

/** Fetches the documents that can be asked about. */
export async function listKnowledgeBases(
  fetchImpl: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<KnowledgeBase[]> {
  const response = await fetchImpl(`${apiBase()}/v1/knowledge-bases`, { signal });
  if (!response.ok) {
    throw new ApiError(`Knowledge base request failed with status ${response.status}`, response.status);
  }
  return parseKnowledgeBaseList(await response.json());
}
