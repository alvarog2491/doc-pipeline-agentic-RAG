import { useCallback, useEffect, useRef, useState } from "react";
import type { ChunkingStrategy } from "@doc-pipeline/shared-types";
import { requestUpload, uploadToS3, validateFile } from "../services/uploads";

export type UploadState =
  | { phase: "idle" }
  | { phase: "requesting"; fileName: string }
  | { phase: "uploading"; fileName: string; progress: number }
  | { phase: "done"; fileName: string }
  | { phase: "error"; message: string };

/**
 * Uploads a PDF straight to S3 through a presigned ticket and tracks its progress.
 *
 * Once the upload finishes the ingestion pipeline takes over server-side (Textract, Bedrock
 * chunking, a new Knowledge Base), so `onUploaded` lets the caller start watching the document
 * list for the new entry.
 */
export function useDocumentUpload(onUploaded: () => void) {
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const upload = useCallback(
    async (file: File, chunking: ChunkingStrategy) => {
      const invalid = validateFile(file);
      if (invalid) {
        setState({ phase: "error", message: invalid });
        return;
      }
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        setState({ phase: "requesting", fileName: file.name });
        const ticket = await requestUpload(file, chunking);
        setState({ phase: "uploading", fileName: file.name, progress: 0 });
        await uploadToS3(
          ticket,
          file,
          (progress) => setState({ phase: "uploading", fileName: file.name, progress }),
          controller.signal,
        );
        setState({ phase: "done", fileName: file.name });
        onUploaded();
      } catch (cause) {
        if (controller.signal.aborted) return;
        setState({
          phase: "error",
          message: cause instanceof Error ? cause.message : "The upload failed. Please try again.",
        });
      } finally {
        abortRef.current = null;
      }
    },
    [onUploaded],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setState({ phase: "idle" });
  }, []);

  const reset = useCallback(() => setState({ phase: "idle" }), []);

  return { state, upload, cancel, reset };
}
