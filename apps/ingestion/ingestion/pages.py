"""Render Textract elements as one Markdown document per page.

Bedrock Knowledge Bases do the chunking and embedding themselves, but they only see the files
they are given. One file per page keeps every chunk attributable to an exact page, which is what
the agent cites, and lets each file carry its page number as metadata.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .elements import Element

_HEADING_LEVEL = {"title": "#", "section_header": "##"}


@dataclass(frozen=True)
class Page:
    """The Markdown of one PDF page.

    Attributes:
        number: One-based page number.
        section: Nearest heading at or before the page, or an empty string.
        markdown: Page content: headings as ``#``/``##``, tables as Markdown tables.
    """

    number: int
    section: str
    markdown: str


def build_pages(elements: Sequence[Element]) -> list[Page]:
    """Group elements by page and render each page as Markdown.

    Pages with no extractable text are omitted. Text recognised inside figures and diagrams is kept as
    ordinary text, since for many PDFs (slides, charts, scans) it is the content.

    Args:
        elements: Document elements in reading order.

    Returns:
        Pages in ascending order.
    """
    by_page: dict[int, list[Element]] = {}
    for element in elements:
        by_page.setdefault(element.page, []).append(element)

    pages: list[Page] = []
    section = ""
    for number in sorted(by_page):
        blocks: list[str] = []
        for element in by_page[number]:
            if element.kind in _HEADING_LEVEL:
                section = element.text
                blocks.append(f"{_HEADING_LEVEL[element.kind]} {element.text}")
            else:
                blocks.append(element.text)
        pages.append(Page(number=number, section=section, markdown="\n\n".join(blocks)))
    return pages
