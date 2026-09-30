"""Test runtime payload validation, event forwarding and feedback."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import main

KB = "ABCDE12345"


class _FakeLangfuse:
    def __init__(self):
        self.updates, self.scores, self.flushed = [], [], 0

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        outer = self

        class _Span:
            def update(self, **values):
                outer.updates.append(values)

        yield _Span()

    def create_score(self, **kwargs):
        self.scores.append(kwargs)

    def flush(self):
        self.flushed += 1


class _FakeAgent:
    def __init__(self, events, excerpts):
        self._events, self._excerpts = events, excerpts
        self.inputs = None

    async def astream(self, inputs, config, stream_mode):
        assert stream_mode == "custom"
        self.inputs, self.config = inputs, config
        for event in self._events:
            yield event

    async def aget_state(self, config):
        return SimpleNamespace(values={"excerpts": self._excerpts})


async def _collect(payload, session_id="sess-1"):
    context = SimpleNamespace(session_id=session_id, request_headers=None)
    return [event async for event in main.invoke(payload, context)]


@pytest.fixture
def langfuse(monkeypatch):
    fake = _FakeLangfuse()
    monkeypatch.setattr(main, "langfuse", fake)
    monkeypatch.setattr(main, "CallbackHandler", lambda: object())
    return fake


async def test_chat_forwards_events_then_resolved_citations(langfuse, monkeypatch):
    excerpts = [
        {"id": 1, "page": 4, "source": "uploads/a.pdf", "section": "S", "text": "t"}
    ]
    agent = _FakeAgent(
        [
            {"route": "easy"},
            {"progress": "Searching…"},
            {"chunk": "Yes "},
            {"chunk": "[[1]] [[7]]"},
        ],
        excerpts,
    )
    monkeypatch.setattr(main, "get_agent", lambda: agent)

    events = await _collect({"prompt": "hello", "knowledgeBaseId": KB})

    assert events[:4] == [
        {"route": "easy"},
        {"progress": "Searching…"},
        {"chunk": "Yes "},
        {"chunk": "[[1]] [[7]]"},
    ]
    assert events[-1] == {
        "citations": [{"id": 1, "page": 4, "source": "uploads/a.pdf", "section": "S"}]
    }
    assert agent.inputs["knowledge_base_id"] == KB
    assert agent.config["configurable"]["thread_id"] == f"sess-1:{KB}"
    assert langfuse.updates[-1]["metadata"]["route"] == "easy"
    assert langfuse.flushed == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "  ", "knowledgeBaseId": KB},
        {"prompt": 3, "knowledgeBaseId": KB},
        {"prompt": "x"},
        {"prompt": "x", "knowledgeBaseId": "not valid!"},
    ],
)
async def test_invalid_chat_payloads_are_rejected(payload, langfuse):
    with pytest.raises(ValueError):
        await _collect(payload)


async def test_non_mapping_payload_is_rejected(langfuse):
    with pytest.raises(TypeError):
        await _collect("nope")


async def test_missing_session_id_is_rejected(langfuse):
    with pytest.raises(ValueError):
        await _collect({"prompt": "x", "knowledgeBaseId": KB}, session_id="")


async def test_feedback_records_a_categorical_session_score(langfuse):
    events = await _collect(
        {"type": "feedback", "outcome": "helpful", "comment": " nice "}
    )

    assert events == [{"status": "ok"}]
    assert langfuse.scores == [
        {
            "name": "user_feedback",
            "value": "helpful",
            "session_id": "sess-1",
            "data_type": "CATEGORICAL",
            "comment": "nice",
        }
    ]
    assert langfuse.flushed == 1


async def test_diagnostics_event_is_opt_in_and_reports_retrieval_counts(
    langfuse, monkeypatch
):
    excerpts = [
        {"id": 1, "page": 4, "source": "uploads/a.pdf", "section": "S", "text": "t"}
    ]

    class Agent(_FakeAgent):
        async def astream(self, inputs, config, stream_mode):
            main.RETRIEVAL_LOG.get().append(
                {"query": "q", "requested": 5, "returned": 1}
            )
            yield {"route": "guide"}

        async def aget_state(self, config):
            return SimpleNamespace(
                values={"excerpts": excerpts, "sections": [1, 2], "prerequisites": [1]}
            )

    monkeypatch.setattr(main, "get_agent", lambda: Agent([], excerpts))

    plain = await _collect({"prompt": "hello", "knowledgeBaseId": KB})
    detailed = await _collect(
        {"prompt": "hello", "knowledgeBaseId": KB, "diagnostics": True}
    )

    assert all("diagnostics" not in event for event in plain)
    assert detailed[-1] == {
        "diagnostics": {
            "route": "guide",
            "retrievals": 1,
            "retrieved": [{"id": 1, "page": 4, "source": "uploads/a.pdf"}],
            "sections": 2,
            "prerequisites": 1,
        }
    }
