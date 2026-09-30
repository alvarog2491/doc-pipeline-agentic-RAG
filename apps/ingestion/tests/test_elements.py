from ingestion.elements import parse_elements


def _line(block_id, text, page=1):
    return {"Id": block_id, "BlockType": "LINE", "Text": text, "Page": page}


def _layout(block_id, block_type, children, page=1, box=(0.1, 0.1, 0.8, 0.1)):
    left, top, width, height = box
    return {
        "Id": block_id,
        "BlockType": block_type,
        "Page": page,
        "Relationships": [{"Type": "CHILD", "Ids": children}],
        "Geometry": {
            "BoundingBox": {"Left": left, "Top": top, "Width": width, "Height": height}
        },
    }


def test_headers_and_footers_are_dropped_and_kinds_mapped():
    blocks = [
        _line("l1", "Confidential"),
        _layout("h", "LAYOUT_HEADER", ["l1"]),
        _line("l2", "Installation"),
        _layout("t", "LAYOUT_SECTION_HEADER", ["l2"]),
        _line("l3", "Mount the unit."),
        _line("l4", "Tighten the bolts."),
        _layout("p", "LAYOUT_TEXT", ["l3", "l4"]),
        _line("l5", "Page 1"),
        _layout("n", "LAYOUT_PAGE_NUMBER", ["l5"]),
    ]

    elements = parse_elements(blocks)

    assert [(e.kind, e.text) for e in elements] == [
        ("section_header", "Installation"),
        ("paragraph", "Mount the unit. Tighten the bolts."),
    ]


def test_list_items_keep_one_line_each():
    blocks = [
        _line("a", "1. Turn off power"),
        _line("b", "2. Open the lid"),
        _layout("l", "LAYOUT_LIST", ["a", "b"]),
    ]

    assert parse_elements(blocks)[0].text == "1. Turn off power\n2. Open the lid"


def test_table_renders_markdown_from_matching_table_block():
    words = [
        {"Id": "w1", "BlockType": "WORD", "Text": "Fault"},
        {"Id": "w2", "BlockType": "WORD", "Text": "Fix"},
        {"Id": "w3", "BlockType": "WORD", "Text": "Noise"},
        {"Id": "w4", "BlockType": "WORD", "Text": "Tighten"},
    ]

    def cell(cid, row, col, word):
        return {
            "Id": cid,
            "BlockType": "CELL",
            "RowIndex": row,
            "ColumnIndex": col,
            "Relationships": [{"Type": "CHILD", "Ids": [word]}],
        }

    table = {
        "Id": "tbl",
        "BlockType": "TABLE",
        "Page": 2,
        "Geometry": {
            "BoundingBox": {"Left": 0.1, "Top": 0.2, "Width": 0.5, "Height": 0.2}
        },
        "Relationships": [{"Type": "CHILD", "Ids": ["c1", "c2", "c3", "c4"]}],
    }
    blocks = [
        *words,
        cell("c1", 1, 1, "w1"),
        cell("c2", 1, 2, "w2"),
        cell("c3", 2, 1, "w3"),
        cell("c4", 2, 2, "w4"),
        table,
        _layout("lt", "LAYOUT_TABLE", [], page=2, box=(0.05, 0.15, 0.9, 0.4)),
    ]

    [element] = parse_elements(blocks)

    assert element.kind == "table"
    assert element.page == 2
    assert element.text == "| Fault | Fix |\n| --- | --- |\n| Noise | Tighten |"


def test_pages_without_layout_fall_back_to_lines():
    blocks = [
        _line("a", "Plain scanned text.", page=1),
        _line("b", "Layout page.", page=2),
        _layout("p", "LAYOUT_TEXT", ["b"], page=2),
    ]

    elements = parse_elements(blocks)

    assert [(e.page, e.text) for e in elements] == [
        (1, "Plain scanned text."),
        (2, "Layout page."),
    ]
