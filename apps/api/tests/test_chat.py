import json
from uuid import uuid4

import pytest
from chat_api.api.v1.endpoints import chat as chat_endpoint
from chat_api.services import agentcore

from tests.conftest import KB_ID


def _parse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line
        )
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def _body(**overrides):
    return {
        "sessionId": str(uuid4()),
        "knowledgeBaseId": KB_ID,
        "prompt": "What is X?",
        **overrides,
    }


@pytest.fixture
def agent(monkeypatch):
    """Scriptable stand-in for the AgentCore stream."""
    state = {"events": [], "error": None, "calls": []}

    async def fake_stream(session_id, knowledge_base_id, prompt):
        state["calls"].append((session_id, knowledge_base_id, prompt))
        for event in state["events"]:
            yield event
        if state["error"]:
            raise state["error"]

    monkeypatch.setattr(agentcore, "stream_chat", fake_stream)

    async def page_link(bucket, key, page, ttl):
        return (
            f"https://s3/{bucket}/{key}#page={page}"
            if key.startswith("uploads/")
            else None
        )

    monkeypatch.setattr(chat_endpoint.documents, "page_link", page_link)
    return state


def test_streams_typed_events_in_order_with_monotonic_sequence(client, agent):
    agent["events"] = [
        {"route": "hard"},
        {"progress": "Searching…"},
        {"chunk": "The "},
        {"chunk": "answer [[1]]."},
        {
            "citations": [
                {"id": 1, "page": 4, "source": "uploads/a.pdf", "section": "S"}
            ]
        },
    ]

    with client.stream("POST", "/v1/chat/stream", json=_body()) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse("".join(response.iter_text()))

    assert [name for name, _ in events] == [
        "route",
        "progress",
        "delta",
        "delta",
        "citations",
        "completed",
    ]
    assert [data["sequence"] for _, data in events] == list(range(6))
    assert len({data["requestId"] for _, data in events}) == 1
    assert events[0][1]["route"] == "hard"
    assert events[2][1]["text"] == "The "
    citation = events[4][1]["citations"][0]
    assert citation == {
        "id": 1,
        "page": 4,
        "section": "S",
        "url": "https://s3/docs-bucket/uploads/a.pdf#page=4",
    }


def test_forwards_session_knowledge_base_and_prompt_to_the_agent(client, agent):
    body = _body()

    client.post("/v1/chat/stream", json=body)

    assert agent["calls"] == [(body["sessionId"], KB_ID, "What is X?")]


def test_citation_links_are_omitted_for_non_upload_keys(client, agent):
    agent["events"] = [
        {"citations": [{"id": 1, "page": 1, "source": "other/x.pdf", "section": ""}]}
    ]

    text = client.post("/v1/chat/stream", json=_body()).text

    assert _parse(text)[0][1]["citations"][0]["url"] is None


def test_agent_failure_becomes_a_generic_error_event(client, agent):
    agent["events"] = [{"chunk": "partial"}]
    agent["error"] = agentcore.AgentCoreResponseError("boom: secret detail")

    events = _parse(client.post("/v1/chat/stream", json=_body()).text)

    assert [name for name, _ in events] == ["delta", "error"]
    error = events[-1][1]
    assert error["code"] == "agent_unavailable"
    assert "secret" not in json.dumps(error)


def test_unexpected_failure_does_not_leak_exception_details(client, agent):
    agent["error"] = RuntimeError("password=hunter2")

    events = _parse(client.post("/v1/chat/stream", json=_body()).text)

    assert events[-1][1]["code"] == "internal_error"
    assert "hunter2" not in json.dumps(events)


def test_unknown_or_unready_knowledge_base_is_a_404_before_streaming(client, agent):
    assert (
        client.post(
            "/v1/chat/stream", json=_body(knowledgeBaseId="ZZZZZ99999")
        ).status_code
        == 404
    )
    assert agent["calls"] == []


def test_processing_documents_cannot_be_chatted_with(client, agent, documents):
    documents[1]["status"] = "PROCESSING"

    assert client.post("/v1/chat/stream", json=_body()).status_code == 404


@pytest.mark.parametrize(
    "override",
    [
        {"prompt": ""},
        {"prompt": "x" * 4001},
        {"sessionId": "not-a-uuid"},
        {"knowledgeBaseId": "short"},
        {"knowledgeBaseId": "../../etc/pw"},
        {"extra": 1},
    ],
)
def test_invalid_requests_are_rejected_before_reaching_the_agent(
    client, agent, override
):
    assert client.post("/v1/chat/stream", json=_body(**override)).status_code == 422
    assert agent["calls"] == []
