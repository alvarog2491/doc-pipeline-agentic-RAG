"""Turn Amazon Textract layout blocks into an ordered list of document elements."""

from __future__ import annotations

from dataclasses import dataclass

HEADING_TYPES = frozenset({"title", "section_header"})
_SKIPPED_LAYOUT = frozenset({"LAYOUT_HEADER", "LAYOUT_FOOTER", "LAYOUT_PAGE_NUMBER"})
_LAYOUT_KINDS = {
    "LAYOUT_TITLE": "title",
    "LAYOUT_SECTION_HEADER": "section_header",
    "LAYOUT_LIST": "list",
    "LAYOUT_TEXT": "paragraph",
    "LAYOUT_KEY_VALUE": "paragraph",
    "LAYOUT_FIGURE": "figure",
    "LAYOUT_TABLE": "table",
}


@dataclass(frozen=True)
class Element:
    """One structural piece of a document in reading order.

    Attributes:
        kind: One of title, section_header, paragraph, list, table or figure.
        text: Plain text, or Markdown for tables.
        page: One-based page number the element starts on.
    """

    kind: str
    text: str
    page: int


def _children(block: dict) -> list[str]:
    """Return the CHILD relationship ids of a Textract block."""
    ids: list[str] = []
    for relationship in block.get("Relationships", []):
        if relationship.get("Type") == "CHILD":
            ids.extend(relationship.get("Ids", []))
    return ids


def _text_of(block: dict, by_id: dict[str, dict], joiner: str = " ") -> str:
    """Join the LINE (or WORD) children of a block into text."""
    parts = []
    for child_id in _children(block):
        child = by_id.get(child_id)
        if child and child["BlockType"] in ("LINE", "WORD"):
            parts.append(child.get("Text", "").strip())
    return joiner.join(part for part in parts if part).strip()


def _table_markdown(table: dict, by_id: dict[str, dict]) -> str:
    """Render a Textract TABLE block as a Markdown table."""
    rows: dict[int, dict[int, str]] = {}
    for cell_id in _children(table):
        cell = by_id.get(cell_id)
        if not cell or cell["BlockType"] != "CELL":
            continue
        text = _text_of(cell, by_id).replace("|", "\\|")
        rows.setdefault(cell["RowIndex"], {})[cell["ColumnIndex"]] = text
    if not rows:
        return ""
    width = max(max(columns) for columns in rows.values())
    lines = []
    for position, row_index in enumerate(sorted(rows)):
        cells = [rows[row_index].get(column, "") for column in range(1, width + 1)]
        lines.append("| " + " | ".join(cells) + " |")
        if position == 0:
            lines.append("|" + " --- |" * width)
    return "\n".join(lines)


def _contains(outer: dict, inner: dict) -> bool:
    """Return whether the centre of ``inner`` lies inside ``outer`` on the same page."""
    if outer.get("Page") != inner.get("Page"):
        return False
    box = outer["Geometry"]["BoundingBox"]
    small = inner["Geometry"]["BoundingBox"]
    x = small["Left"] + small["Width"] / 2
    y = small["Top"] + small["Height"] / 2
    return (
        box["Left"] <= x <= box["Left"] + box["Width"]
        and box["Top"] <= y <= box["Top"] + box["Height"]
    )


def parse_elements(blocks: list[dict]) -> list[Element]:
    """Convert Textract ``LAYOUT`` + ``TABLES`` blocks into ordered elements.

    Headers, footers and page numbers are dropped. Tables are rendered as Markdown by
    matching each layout table to the ``TABLE`` block it covers. A page with no layout
    blocks at all falls back to its plain ``LINE`` blocks so no text is lost.

    Args:
        blocks: Every block returned by ``GetDocumentAnalysis``, in response order.

    Returns:
        Elements in reading order with empty ones removed.
    """
    by_id = {block["Id"]: block for block in blocks}
    tables = [block for block in blocks if block["BlockType"] == "TABLE"]
    layout_pages = {
        block.get("Page", 1)
        for block in blocks
        if block["BlockType"].startswith("LAYOUT_")
    }

    elements: list[Element] = []
    for block in blocks:
        block_type = block["BlockType"]
        page = block.get("Page", 1)
        if block_type in _SKIPPED_LAYOUT:
            continue
        if block_type in _LAYOUT_KINDS:
            kind = _LAYOUT_KINDS[block_type]
            if kind == "table":
                match = next((t for t in tables if _contains(block, t)), None)
                text = (
                    _table_markdown(match, by_id) if match else _text_of(block, by_id)
                )
            elif kind == "list":
                text = _text_of(block, by_id, joiner="\n")
            else:
                text = _text_of(block, by_id)
        elif block_type == "LINE" and page not in layout_pages:
            kind, text = "paragraph", block.get("Text", "").strip()
        else:
            continue
        if text:
            elements.append(Element(kind=kind, text=text, page=page))
    return elements
