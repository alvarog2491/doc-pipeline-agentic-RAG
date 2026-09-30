import {
  MAX_UPLOAD_BYTES,
  parseUploadTicket,
  type ChunkingStrategy,
  type UploadTicket,
} from "@doc-pipeline/shared-types";
import { ApiError, apiBase } from "./chatApi";

/** Why a file cannot be uploaded, or null when it can. Mirrors the API's checks. */
export function validateFile(file: { name: string; size: number; type: string }): string | null {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "Only PDF files can be uploaded.";
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) {
    return `That file is larger than ${Math.round(MAX_UPLOAD_BYTES / (1024 * 1024))} MB.`;
  }
  return null;
}

/** Asks the API for a presigned upload; the PDF itself never passes through the API. */
export async function requestUpload(
  file: { name: string; size: number },
  chunking: ChunkingStrategy | undefined,
  fetchImpl: typeof fetch = fetch,
): Promise<UploadTicket> {
  const response = await fetchImpl(`${apiBase()}/v1/documents/upload`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      sizeBytes: file.size,
      // Omitted for the default so the server-side default applies.
      ...(chunking && chunking !== "semantic" ? { chunking } : {}),
    }),
  });
  if (!response.ok) {
    let detail = `Upload request failed with status ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // keep the generic message
    }
    throw new ApiError(detail, response.status);
  }
  return parseUploadTicket(await response.json());
}

/** The slice of XMLHttpRequest the uploader uses, so tests can substitute it. */
export interface UploadRequestLike {
  upload: { onprogress: ((event: { loaded: number; total: number; lengthComputable: boolean }) => void) | null };
  onload: (() => void) | null;
  onerror: (() => void) | null;
  onabort: (() => void) | null;
  status: number;
  open(method: string, url: string): void;
  send(body: FormData): void;
  abort(): void;
}

/**
 * Posts the file to S3 with the ticket's fields and reports progress.
 *
 * `fetch` cannot report upload progress, so this uses XMLHttpRequest. The signed fields come first
 * and the file last, as S3 requires.
 *
 * @throws Error when S3 rejects the upload, the network fails, or `signal` aborts it.
 */
export function uploadToS3(
  ticket: UploadTicket,
  file: Blob,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
  createRequest: () => UploadRequestLike = () => new XMLHttpRequest() as unknown as UploadRequestLike,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = createRequest();
    const form = new FormData();
    for (const [name, value] of Object.entries(ticket.fields)) form.append(name, value);
    form.append("file", file);

    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(1);
        resolve();
      } else {
        reject(new Error(`The upload was rejected (status ${request.status}).`));
      }
    };
    request.onerror = () => reject(new Error("The upload failed. Check your connection and try again."));
    request.onabort = () => reject(new Error("The upload was cancelled."));
    signal?.addEventListener("abort", () => request.abort(), { once: true });

    request.open("POST", ticket.url);
    request.send(form);
  });
}
