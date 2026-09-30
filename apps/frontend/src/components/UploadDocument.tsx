import { useRef, useState, type ChangeEvent } from "react";
import type { ChunkingStrategy } from "@doc-pipeline/shared-types";
import { useDocumentUpload } from "../hooks/useDocumentUpload";

interface Props {
  /** Called when a file has finished uploading and ingestion has started. */
  onUploaded: () => void;
}

const CHUNKING_LABEL: Record<ChunkingStrategy, string> = {
  semantic: "Automatic (semantic)",
  hierarchical: "Long documents (hierarchical)",
  fixed: "Uniform text (fixed size)",
  none: "One chunk per page",
};

/** Upload a PDF; it is ingested into its own Knowledge Base and appears in the document list. */
export function UploadDocument({ onUploaded }: Props) {
  const { state, upload, cancel, reset } = useDocumentUpload(onUploaded);
  const [chunking, setChunking] = useState<ChunkingStrategy>("semantic");
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = state.phase === "requesting" || state.phase === "uploading";

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // allow choosing the same file again
    if (file) void upload(file, chunking);
  };

  return (
    <div className="upload">
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="upload__input"
        aria-label="Choose a PDF to upload"
        onChange={handleChange}
        disabled={busy}
      />
      <select
        className="kb-select__control upload__chunking"
        aria-label="How to split the document"
        value={chunking}
        onChange={(event) => setChunking(event.target.value as ChunkingStrategy)}
        disabled={busy}
        title="How the document is split into searchable chunks"
      >
        {(Object.keys(CHUNKING_LABEL) as ChunkingStrategy[]).map((strategy) => (
          <option key={strategy} value={strategy}>
            {CHUNKING_LABEL[strategy]}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="feedback-button"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
      >
        Upload PDF
      </button>

      <div className="upload__status" role="status" aria-live="polite">
        {state.phase === "requesting" && <span>Preparing {state.fileName}…</span>}
        {state.phase === "uploading" && (
          <>
            <progress className="upload__progress" value={state.progress} max={1} aria-label="Upload progress" />
            <span>
              {state.fileName} {Math.round(state.progress * 100)}%
            </span>
            <button type="button" className="feedback-button" onClick={cancel}>
              Cancel
            </button>
          </>
        )}
        {state.phase === "done" && (
          <>
            <span>
              {state.fileName} uploaded — it appears in the list while it is processed.
            </span>
            <button type="button" className="feedback-button" onClick={reset} aria-label="Dismiss">
              ✕
            </button>
          </>
        )}
        {state.phase === "error" && (
          <>
            <span className="upload__error" role="alert">
              {state.message}
            </span>
            <button type="button" className="feedback-button" onClick={reset} aria-label="Dismiss">
              ✕
            </button>
          </>
        )}
      </div>
    </div>
  );
}
