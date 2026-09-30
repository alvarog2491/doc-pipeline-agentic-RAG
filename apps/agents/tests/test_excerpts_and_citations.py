from citations import cited_ids, resolve_citations
from excerpts import ExcerptPool, render_excerpts
from tests.support import passage


def test_pool_numbers_new_passages_and_reuses_ids_for_duplicates():
    pool = ExcerptPool()

    first = pool.add([passage("a", 1), passage("b", 2)])
    again = pool.add([passage("b", 2), passage("c", 3)])

    assert [e["id"] for e in first] == [1, 2]
    assert [e["id"] for e in again] == [2, 3]
    assert len(pool.items) == 3


def test_pool_continues_numbering_from_existing_excerpts():
    pool = ExcerptPool(ExcerptPool().add([passage("a")]))

    assert pool.add([passage("z")])[0]["id"] == 2


def test_render_excerpts_marks_ids_and_pages():
    text = render_excerpts(ExcerptPool().add([passage("Body", 7)]))

    assert text == "[[1]] (page 7)\nBody"


def test_cited_ids_are_distinct_and_in_first_use_order():
    assert cited_ids("x [[3]] y [[1]][[3]] z [[2]]") == [3, 1, 2]


def test_resolve_citations_drops_unknown_markers():
    excerpts = ExcerptPool().add([passage("a", 4, "Intro")])

    assert resolve_citations("fact [[1]] and [[9]]", excerpts) == [
        {"id": 1, "page": 4, "source": "uploads/manual.pdf", "section": "Intro"}
    ]
