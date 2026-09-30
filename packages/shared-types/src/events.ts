/**
 * Public wire contract of the REST + Server-Sent Events API (major version `v1`).
 *
 * `POST /v1/chat/stream` answers with an SSE stream whose `event:` field is one of the
 * `type` values below and whose `data:` field is the JSON of that event. Every event carries
 * `requestId` and a monotonic `sequence`. Changes within v1 are additive; a breaking change
 * needs a new `/v2` path. Keep chat_api/core/protocol.py in step with this file.
 */

export const API_VERSION = "v1" as const;
export const MAX_PROMPT_CHARACTERS = 4000;

export type Route = "easy" | "hard" | "guide";

export interface ChatRequest {
  sessionId: string;
  knowledgeBaseId: string;
  prompt: string;
}

interface EventBase {
  requestId: string;
  sequence: number;
}

export interface RouteEvent extends EventBase {
  type: "route";
  route: Route;
}

/** A transient status line while the agent works; not part of the answer text. */
export interface ProgressEvent extends EventBase {
  type: "progress";
  text: string;
}

export interface DeltaEvent extends EventBase {
  type: "delta";
  text: string;
}

export interface Citation {
  id: number;
  page: number;
  section: string;
  /** Short-lived link to the PDF, or null when it could not be produced. */
  url: string | null;
}

export interface CitationsEvent extends EventBase {
  type: "citations";
  citations: Citation[];
}

export interface CompletedEvent extends EventBase {
  type: "completed";
}

export type ErrorCode = "agent_unavailable" | "internal_error";

export interface ErrorEvent extends EventBase {
  type: "error";
  code: ErrorCode;
  message: string;
}

export type ServerEvent =
  | RouteEvent
  | ProgressEvent
  | DeltaEvent
  | CitationsEvent
  | CompletedEvent
  | ErrorEvent;

export type KnowledgeBaseStatus = "PROCESSING" | "INDEXING" | "READY" | "FAILED";

export interface KnowledgeBase {
  id: string;
  name: string;
  status: KnowledgeBaseStatus;
  pages: number | null;
  updatedAt: string | null;
}

const ROUTES: readonly string[] = ["easy", "hard", "guide"];
const STATUSES: readonly string[] = ["PROCESSING", "INDEXING", "READY", "FAILED"];
const ERROR_CODES: readonly string[] = ["agent_unavailable", "internal_error"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCitation(value: unknown): value is Citation {
  return (
    isRecord(value) &&
    Number.isSafeInteger(value.id) &&
    Number.isSafeInteger(value.page) &&
    typeof value.section === "string" &&
    (typeof value.url === "string" || value.url === null)
  );
}

/**
 * Validates one decoded SSE event before the UI trusts it.
 *
 * @param name The SSE `event:` field.
 * @param data The parsed JSON of the `data:` field.
 * @returns The typed event.
 * @throws Error when the event is unknown or malformed.
 */
export function parseServerEvent(name: string, data: unknown): ServerEvent {
  if (
    !isRecord(data) ||
    data.type !== name ||
    typeof data.requestId !== "string" ||
    !Number.isSafeInteger(data.sequence) ||
    (data.sequence as number) < 0
  ) {
    throw new Error("Unsupported server event");
  }

  switch (name) {
    case "route":
      if (typeof data.route === "string" && ROUTES.includes(data.route)) {
        return data as unknown as RouteEvent;
      }
      break;
    case "progress":
    case "delta":
      if (typeof data.text === "string") {
        return data as unknown as ProgressEvent | DeltaEvent;
      }
      break;
    case "citations":
      if (Array.isArray(data.citations) && data.citations.every(isCitation)) {
        return data as unknown as CitationsEvent;
      }
      break;
    case "completed":
      return data as unknown as CompletedEvent;
    case "error":
      if (
        typeof data.code === "string" &&
        ERROR_CODES.includes(data.code) &&
        typeof data.message === "string"
      ) {
        return data as unknown as ErrorEvent;
      }
      break;
  }
  throw new Error("Unsupported server event");
}

/**
 * Validates the body of `GET /v1/knowledge-bases`.
 *
 * @throws Error when the payload is not a list of well-formed knowledge bases.
 */
export function parseKnowledgeBaseList(data: unknown): KnowledgeBase[] {
  if (!isRecord(data) || !Array.isArray(data.knowledgeBases)) {
    throw new Error("Unsupported knowledge base list");
  }
  return data.knowledgeBases.map((item) => {
    if (
      !isRecord(item) ||
      typeof item.id !== "string" ||
      typeof item.name !== "string" ||
      typeof item.status !== "string" ||
      !STATUSES.includes(item.status)
    ) {
      throw new Error("Unsupported knowledge base list");
    }
    return {
      id: item.id,
      name: item.name,
      status: item.status as KnowledgeBaseStatus,
      pages: typeof item.pages === "number" ? item.pages : null,
      updatedAt: typeof item.updatedAt === "string" ? item.updatedAt : null,
    };
  });
}

/** Largest PDF the browser offers to upload; the API enforces its own (configurable) limit. */
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

export type ChunkingStrategy = "semantic" | "hierarchical" | "fixed" | "none";
export const CHUNKING_STRATEGIES: readonly ChunkingStrategy[] = ["semantic", "hierarchical", "fixed", "none"];

/** Body of `POST /v1/documents/upload`. Omit `chunking` for the semantic default. */
export interface UploadRequest {
  filename: string;
  sizeBytes: number;
  contentType?: "application/pdf";
  chunking?: ChunkingStrategy;
  maxTokens?: number;
}

/** A presigned S3 POST: send `fields` then the file, as multipart form data, to `url`. */
export interface UploadTicket {
  url: string;
  fields: Record<string, string>;
  key: string;
  maxBytes: number;
}

/**
 * Validates the response of `POST /v1/documents/upload` before the browser posts a file to it.
 *
 * @throws Error when the ticket is malformed or does not point at an https URL.
 */
export function parseUploadTicket(data: unknown): UploadTicket {
  if (
    !isRecord(data) ||
    typeof data.url !== "string" ||
    !data.url.startsWith("https://") ||
    typeof data.key !== "string" ||
    typeof data.maxBytes !== "number" ||
    !isRecord(data.fields) ||
    !Object.values(data.fields).every((value) => typeof value === "string")
  ) {
    throw new Error("Unsupported upload ticket");
  }
  return {
    url: data.url,
    key: data.key,
    maxBytes: data.maxBytes,
    fields: data.fields as Record<string, string>,
  };
}
