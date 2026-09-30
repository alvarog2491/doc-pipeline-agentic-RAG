import json
import re

from fixture.pdf_builder import HANDBOOK_JSON, build_pdf


def test_pdf_has_one_page_per_handbook_section_and_a_valid_xref_table():
    document = json.loads(HANDBOOK_JSON.read_text())
    pdf = build_pdf(document)

    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type /Page\b", pdf)) == len(document["pages"]) == 6
    xref_start = int(re.search(rb"startxref\n(\d+)", pdf).group(1))
    assert pdf[xref_start : xref_start + 4] == b"xref"
    entries = re.findall(rb"(\d{10}) 00000 n ", pdf)
    for number, offset in enumerate(entries, start=1):
        assert pdf[int(offset) :].startswith(f"{number} 0 obj".encode())


def test_page_text_is_escaped_and_present():
    pdf = build_pdf({"pages": [{"heading": "A (b) \\ c", "lines": ["Max 6 bar"]}]})

    assert rb"(A \(b\) \\ c) Tj" in pdf
    assert b"(Max 6 bar) Tj" in pdf


def test_dataset_facts_are_backed_by_the_handbook_pages():
    """Every expected page and key fact in the datasets must exist in the fixture text."""
    from base_dataset_creator import RAW_DATASETS_DIR
    from evaluators.text import fact_present

    document = json.loads(HANDBOOK_JSON.read_text())
    pages = [" ".join([p["heading"], *p["lines"]]) for p in document["pages"]]

    for path in RAW_DATASETS_DIR.glob("*.json"):
        for item in json.loads(path.read_text())["items"]:
            meta = item["metadata"]
            if meta.get("answerable") is False:
                continue
            expected = meta.get("expected_pages", [])
            assert all(1 <= page <= len(pages) for page in expected), item["id"]
            joined = (
                " ".join(pages[page - 1] for page in expected)
                if expected
                else " ".join(pages)
            )
            for fact in meta.get("key_facts", []):
                assert fact_present(joined, fact), (item["id"], fact)
