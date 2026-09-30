"""Build the evaluation handbook as a minimal, text-only PDF (no committed binary)."""

from __future__ import annotations

import json
from pathlib import Path

HANDBOOK_JSON = Path(__file__).with_name("handbook.json")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_stream(heading: str, lines: list[str]) -> bytes:
    commands = [
        "BT",
        "/F2 18 Tf",
        "56 780 Td",
        f"({_escape(heading)}) Tj",
        "/F1 12 Tf",
        "0 -34 Td",
    ]
    for line in lines:
        commands += [f"({_escape(line)}) Tj", "0 -22 Td"]
    commands.append("ET")
    return "\n".join(commands).encode("latin-1", "replace")


def build_pdf(document: dict | None = None) -> bytes:
    """Render the handbook JSON as a PDF with one section per page.

    Args:
        document: Parsed handbook (``pages`` of ``heading`` + ``lines``); defaults to
            ``handbook.json`` beside this module.

    Returns:
        PDF bytes with a valid cross-reference table.
    """
    document = document or json.loads(HANDBOOK_JSON.read_text())
    pages = document["pages"]
    objects: list[bytes] = [b""] * (5 + 2 * len(pages))  # index 0 unused
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(len(pages)))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
    for i, page in enumerate(pages):
        page_id, content_id = 5 + 2 * i, 6 + 2 * i
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        stream = _page_stream(page["heading"], page["lines"])
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0] * len(objects)
    for number in range(1, len(objects)):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects)}\n0000000000 65535 f \n".encode()
    for number in range(1, len(objects)):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)
