"""Extract the ``[[n]]`` excerpt markers an answer cites and resolve them to page metadata."""

from __future__ import annotations

import re
from collections.abc import Iterable

from excerpts import Excerpt

_MARKER = re.compile(r"\[\[(\d+)\]\]")


def cited_ids(answer: str) -> list[int]:
    """Return the distinct excerpt ids an answer cites, in first-use order."""
    return list(dict.fromkeys(int(match) for match in _MARKER.findall(answer)))


def resolve_citations(answer: str, excerpts: Iterable[Excerpt]) -> list[dict]:
    """Map the markers in an answer to the excerpts they point at.

    Markers that name no retrieved excerpt are dropped; the evaluation suite scores how
    often that happens.

    Args:
        answer: Full answer text.
        excerpts: Every excerpt numbered during the turn.

    Returns:
        One ``{id, page, source, section}`` mapping per valid marker.
    """
    by_id = {excerpt["id"]: excerpt for excerpt in excerpts}
    return [
        {
            "id": i,
            "page": by_id[i]["page"],
            "source": by_id[i]["source"],
            "section": by_id[i]["section"],
        }
        for i in cited_ids(answer)
        if i in by_id
    ]
