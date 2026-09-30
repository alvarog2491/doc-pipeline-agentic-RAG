import asyncio
import json

import httpx
import pytest
from chat_api.services import agentcore


class _FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("POST", "http://x"), response=self
            )


class _FakeAsyncClient:
    def __init__(self, *args, captured, status_code=200, **kwargs):
        self._captured = captured
        self._status_code = status_code
        self.is_closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, content, headers, timeout=None):
        self._captured.update(url=url, content=content, headers=headers)
        return _FakeResponse(self._status_code)

    async def aclose(self):
        self.is_closed = True


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(agentcore, "_client", None)
    monkeypatch.setenv("AGENT_GATEWAY_URL", "http://agents:8080")
    monkeypatch.setattr(
        agentcore, "sigv4_sign", lambda method, url, body, extra: dict(extra)
    )


def test_agentcore_http_client_is_reused(monkeypatch):
    clients = []

    def build_client(*args, **kwargs):
        client = _FakeAsyncClient(*args, captured={}, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(agentcore.httpx, "AsyncClient", build_client)

    assert agentcore._get_client() is agentcore._get_client()
    assert len(clients) == 1


def test_submit_feedback_posts_feedback_payload_to_invocations(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        agentcore.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(*a, captured=captured, **k),
    )

    asyncio.run(
        agentcore.submit_feedback(
            "sess-1", outcome="not_helpful", comment="no citations"
        )
    )

    assert captured["url"] == "http://agents:8080/invocations"
    assert json.loads(captured["content"]) == {
        "type": "feedback",
        "outcome": "not_helpful",
        "comment": "no citations",
    }
    assert (
        captured["headers"]["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] == "sess-1"
    )


def test_submit_feedback_raises_on_gateway_error(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        agentcore.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(*a, captured=captured, status_code=500, **k),
    )

    with pytest.raises(agentcore.AgentCoreResponseError):
        asyncio.run(
            agentcore.submit_feedback("sess-1", outcome="helpful", comment=None)
        )


def test_submit_feedback_translates_gateway_connection_error(monkeypatch):
    class _UnavailableClient:
        is_closed = False

        async def post(self, url, *, content, headers, timeout=None):
            request = httpx.Request("POST", url)
            raise httpx.ConnectError("All connection attempts failed", request=request)

    monkeypatch.setattr(agentcore, "_client", _UnavailableClient())

    with pytest.raises(
        agentcore.AgentCoreResponseError, match="could not be reached"
    ) as exc_info:
        asyncio.run(
            agentcore.submit_feedback("sess-1", outcome="helpful", comment=None)
        )

    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)


class _FakeStreamResponse:
    def __init__(self, lines):
        self.status_code = 200
        self.headers = {"content-type": "text/event-stream"}
        self._lines = lines

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeStreamingClient:
    def __init__(self, lines):
        self._lines = lines
        self.is_closed = False

    def stream(self, method, url, *, content, headers, timeout=None):
        return _FakeStreamResponse(self._lines)


async def test_stream_chat_yields_decoded_agent_events_and_stops_at_done(monkeypatch):
    lines = [
        'data: {"route": "easy"}',
        ": keep-alive",
        "data: not json",
        'data: {"chunk": "The answer "}',
        'data: {"citations": []}',
        "data: [DONE]",
        'data: {"chunk": "ignored"}',
    ]
    monkeypatch.setattr(agentcore, "_client", _FakeStreamingClient(lines))

    events = [
        e async for e in agentcore.stream_chat("sess-1", "ABCDE12345", "max pressure?")
    ]

    assert events == [{"route": "easy"}, {"chunk": "The answer "}, {"citations": []}]


async def test_stream_chat_sends_prompt_knowledge_base_and_session_header(monkeypatch):
    seen = {}

    class Client(_FakeStreamingClient):
        def stream(self, method, url, *, content, headers, timeout=None):
            seen.update(url=url, body=json.loads(content), headers=headers)
            return super().stream(method, url, content=content, headers=headers)

    monkeypatch.setattr(agentcore, "_client", Client([]))

    [e async for e in agentcore.stream_chat("sess-9", "ABCDE12345", "hello")]

    assert seen["url"] == "http://agents:8080/invocations"
    assert seen["body"] == {"prompt": "hello", "knowledgeBaseId": "ABCDE12345"}
    assert seen["headers"]["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] == "sess-9"


async def test_stream_chat_translates_gateway_failures(monkeypatch):
    class Client:
        is_closed = False

        def stream(self, *args, **kwargs):
            raise httpx.ConnectError("down", request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(agentcore, "_client", Client())

    with pytest.raises(agentcore.AgentCoreResponseError, match="could not be reached"):
        [e async for e in agentcore.stream_chat("s", "ABCDE12345", "hi")]
