import type { Citation } from "@doc-pipeline/shared-types";

// A run of [[n]] markers plus the whitespace before it.
const MARKER_RUN = /\s*(?:\[\[\d+\]\])+/g;
// A marker still arriving at the end of the text while streaming: "[", "[[", "[[12", "[[12]".
const PARTIAL_MARKER_TAIL = /\s*\[\[?\d*\]?$/;

/**
 * Replaces the `[[n]]` excerpt markers in an answer with page links.
 *
 * Markers the server has not resolved yet (citations arrive after the last delta) and
 * markers that name no citation are hidden, so raw syntax is never shown. Duplicate pages in
 * one run collapse into one link.
 */
export function renderCitations(text: string, citations: Citation[] | undefined): string {
  const byId = new Map((citations ?? []).map((citation) => [citation.id, citation]));
  const withoutPartial = text.replace(PARTIAL_MARKER_TAIL, "");

  return withoutPartial.replace(MARKER_RUN, (run) => {
    const seenPages = new Set<number>();
    const links: string[] = [];
    for (const [, id] of run.matchAll(/\[\[(\d+)\]\]/g)) {
      const citation = byId.get(Number(id));
      if (!citation || seenPages.has(citation.page)) continue;
      seenPages.add(citation.page);
      links.push(
        citation.url ? `[Page ${citation.page}](${citation.url})` : `(Page ${citation.page})`,
      );
    }
    return links.length ? ` ${links.join(" ")}` : "";
  });
}
