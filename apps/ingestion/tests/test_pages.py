from ingestion.elements import Element
from ingestion.pages import build_pages


def test_pages_group_elements_and_render_headings_and_tables_as_markdown():
    table = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    elements = [
        Element("title", "Handbook", 1),
        Element("paragraph", "Intro text.", 1),
        Element("section_header", "Install", 2),
        Element("paragraph", "Step one.", 2),
        Element("table", table, 2),
    ]

    pages = build_pages(elements)

    assert [p.number for p in pages] == [1, 2]
    assert pages[0].markdown == "# Handbook\n\nIntro text."
    assert pages[1].markdown == f"## Install\n\nStep one.\n\n{table}"


def test_a_page_inherits_the_section_of_the_previous_heading():
    elements = [
        Element("section_header", "Safety", 1),
        Element("paragraph", "Wear gloves.", 1),
        Element("paragraph", "Continued on the next page.", 2),
    ]

    pages = build_pages(elements)

    assert [p.section for p in pages] == ["Safety", "Safety"]


def test_text_inside_figures_is_kept_and_pages_are_ordered():
    elements = [
        Element("paragraph", "Second.", 3),
        Element("figure", "Q3 revenue: 4.2M", 2),
        Element("paragraph", "First.", 1),
    ]

    pages = build_pages(elements)

    assert [(p.number, p.markdown) for p in pages] == [
        (1, "First."),
        (2, "Q3 revenue: 4.2M"),
        (3, "Second."),
    ]


def test_no_elements_yield_no_pages():
    assert build_pages([]) == []
