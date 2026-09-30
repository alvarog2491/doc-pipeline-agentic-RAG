import type { KnowledgeBase } from "@doc-pipeline/shared-types";

interface Props {
  knowledgeBases: KnowledgeBase[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}

const STATUS_LABEL: Record<KnowledgeBase["status"], string> = {
  READY: "",
  PROCESSING: " (extracting…)",
  INDEXING: " (indexing…)",
  FAILED: " (failed)",
};

/** Dropdown of uploaded documents; only `READY` ones can be selected. */
export function KnowledgeBaseSelect({ knowledgeBases, selectedId, loading, onSelect, onRefresh }: Props) {
  return (
    <div className="kb-select">
      <label className="kb-select__label" htmlFor="kb-select">
        Document
      </label>
      <select
        id="kb-select"
        className="kb-select__control"
        value={selectedId ?? ""}
        onChange={(event) => onSelect(event.target.value)}
        disabled={knowledgeBases.length === 0}
      >
        <option value="" disabled>
          {knowledgeBases.length === 0 ? "No documents yet" : "Select a document…"}
        </option>
        {knowledgeBases.map((kb) => (
          <option key={kb.id} value={kb.id} disabled={kb.status !== "READY"}>
            {kb.name}
            {STATUS_LABEL[kb.status]}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="feedback-button kb-select__refresh"
        onClick={onRefresh}
        disabled={loading}
        aria-label="Refresh documents"
      >
        ↻
      </button>
    </div>
  );
}
