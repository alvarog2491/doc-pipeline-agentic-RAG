def test_lists_documents_sorted_with_status_and_kb_id(client):
    body = client.get("/v1/knowledge-bases").json()

    assert body == {
        "knowledgeBases": [
            {
                "id": "ABCDE12345",
                "name": "Alpha manual",
                "status": "READY",
                "pages": 12,
                "updatedAt": None,
            },
            {
                "id": "b-1",
                "name": "Bravo guide",
                "status": "PROCESSING",
                "pages": None,
                "updatedAt": None,
            },
        ]
    }


def test_health_reports_ok(client):
    assert client.get("/health").json() == {"status": "ok", "version": "v1"}


def test_indexing_documents_are_listed_but_not_chat_ready(client, documents):
    documents.append(
        {
            "doc_id": "c-1",
            "name": "Charlie",
            "status": "INDEXING",
            "kb_id": "KBINDEX001",
        }
    )

    statuses = {
        kb["name"]: kb["status"]
        for kb in client.get("/v1/knowledge-bases").json()["knowledgeBases"]
    }

    assert statuses["Charlie"] == "INDEXING"
