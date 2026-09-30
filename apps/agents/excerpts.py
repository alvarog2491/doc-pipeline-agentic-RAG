"""Numbered manual excerpts and the citation metadata attached to them."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict


class Passage(TypedDict):
    """One retrieved chunk before it has been numbered.

    Attributes:
        text: Chunk text, prefixed with its section heading.
        page: First page the chunk covers.
        source: S3 key of the PDF the chunk came from.
        section: Nearest heading, or an empty string.
    """

    text: str
    page: int
    source: str
    section: str


class Excerpt(Passage):
    """A passage with the identifier the model cites as ``[[id]]``."""

    id: int


class ExcerptPool:
    """Assign stable per-turn identifiers to passages and deduplicate repeats.

    Args:
        existing: Excerpts already numbered earlier in the same turn.
    """

    def __init__(self, existing: Iterable[Excerpt] = ()) -> None:
        self._items: list[Excerpt] = list(existing)
        self._seen = {(item["source"], item["text"]): item for item in self._items}

    def add(self, passages: Iterable[Passage]) -> list[Excerpt]:
        """Number new passages and return the excerpts they map to, in input order.

        Args:
            passages: Retrieved passages; ones already in the pool reuse their id.

        Returns:
            One excerpt per input passage.
        """
        result: list[Excerpt] = []
        for passage in passages:
            key = (passage["source"], passage["text"])
            excerpt = self._seen.get(key)
            if excerpt is None:
                excerpt = Excerpt(**passage, id=len(self._items) + 1)
                self._items.append(excerpt)
                self._seen[key] = excerpt
            result.append(excerpt)
        return result

    @property
    def items(self) -> list[Excerpt]:
        """Every excerpt numbered so far."""
        return list(self._items)


def render_excerpts(excerpts: Iterable[Excerpt]) -> str:
    """Format excerpts as the numbered context block the model reads.

    Args:
        excerpts: Excerpts to render.

    Returns:
        ``[[id]] (page N)`` headed blocks separated by blank lines, or an empty string.
    """
    return "\n\n".join(
        f"[[{item['id']}]] (page {item['page']})\n{item['text']}" for item in excerpts
    )
