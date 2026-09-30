import pytest

import retrieval


def test_passages_map_metadata_and_skip_empty_text():
    results = [
        {
            "content": {"text": "hello"},
            "metadata": {"page": 3, "source": "uploads/a.pdf", "section": "-"},
        },
        {"content": {"text": ""}, "metadata": {}},
        {
            "content": {"text": "world"},
            "metadata": {"page": "5", "source": "uploads/a.pdf", "section": "Intro"},
        },
    ]

    assert retrieval._passages(results) == [
        {"text": "hello", "page": 3, "source": "uploads/a.pdf", "section": ""},
        {"text": "world", "page": 5, "source": "uploads/a.pdf", "section": "Intro"},
    ]


async def test_retrieve_rejects_malformed_knowledge_base_ids():
    with pytest.raises(ValueError):
        await retrieval.retrieve("../etc", "q", 5)


async def test_retrieve_calls_bedrock_with_the_requested_size(monkeypatch):
    seen = {}

    class Client:
        def retrieve(self, **kwargs):
            seen.update(kwargs)
            return {
                "retrievalResults": [
                    {"content": {"text": "t"}, "metadata": {"page": 1}}
                ]
            }

    monkeypatch.setattr(retrieval, "_get_client", lambda: Client())

    passages = await retrieval.retrieve("ABCDE12345", "why?", 7)

    assert seen["knowledgeBaseId"] == "ABCDE12345"
    assert (
        seen["retrievalConfiguration"]["vectorSearchConfiguration"]["numberOfResults"]
        == 7
    )
    assert passages[0]["text"] == "t"
