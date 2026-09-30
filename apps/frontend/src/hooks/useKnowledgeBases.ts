import { useCallback, useEffect, useState } from "react";
import type { KnowledgeBase } from "@doc-pipeline/shared-types";
import { listKnowledgeBases } from "../services/chatApi";

const POLL_MS = 10_000;
// Right after an upload the registry entry may not exist yet, so poll quickly for a while.
const WATCH_POLL_MS = 3_000;
const WATCH_DURATION_MS = 90_000;

/**
 * Loads the selectable documents and keeps polling while any is still being processed, so a
 * freshly uploaded PDF appears in the dropdown without a page reload.
 */
export function useKnowledgeBases() {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [watchUntil, setWatchUntil] = useState(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      setKnowledgeBases(await listKnowledgeBases(fetch, signal));
      setError(null);
    } catch {
      if (!signal?.aborted) setError("Could not load the document list.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  const processing = knowledgeBases.some((kb) => kb.status === "PROCESSING" || kb.status === "INDEXING");

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const watching = watchUntil > Date.now();

  useEffect(() => {
    if (!processing && !watching) return;
    const timer = setInterval(() => {
      void refresh();
      if (watchUntil && Date.now() >= watchUntil) setWatchUntil(0);
    }, watching ? WATCH_POLL_MS : POLL_MS);
    return () => clearInterval(timer);
  }, [processing, watching, watchUntil, refresh]);

  /** Poll quickly for a while, so a document that was just uploaded shows up promptly. */
  const watch = useCallback(() => {
    setWatchUntil(Date.now() + WATCH_DURATION_MS);
    void refresh();
  }, [refresh]);

  return { knowledgeBases, loading, error, refresh: () => refresh(), watch };
}
