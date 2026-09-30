"""Test the evaluation Gateway client: event folding, timings and retries."""

import json
from typing import ClassVar

import agent_client
import httpx
import pytest


class _Response:
    status_code = 200

    def __init__(self, lines):
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


class _Client:
    captured: ClassVar[dict] = {}

    def __init__(self, lines, *args, **kwargs):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, *, content, headers):
        _Client.captured = {"url": url, "body": json.loads(content), "headers": headers}
        return _Response(self._lines)


@pytest.fixture(autouse=True)
def _gateway(monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_URL", "http://gateway")
    monkeypatch.setattr(
        agent_client, "sigv4_sign", lambda method, url, body, headers: dict(headers)
    )


def _events(*events):
    return [f"data: {json.dumps(event)}" for event in events] + ["data: [DONE]"]


async def test_folds_the_event_stream_into_a_timed_run(monkeypatch):
    lines = _events(
        {"route": "guide"},
        {"progress": "Planning…"},
        {"chunk": "1. Do "},
        {"chunk": "it."},
        {"citations": [{"id": 1, "page": 3}]},
        {"diagnostics": {"retrievals": 4, "sections": 3}},
    )
    monkeypatch.setattr(
        agent_client.httpx, "AsyncClient", lambda *a, **k: _Client(lines)
    )

    run = await agent_client.invoke_agent(
        "How?",
        "ABCDE12345",
        "sess",
        trace_context={"trace_id": "a" * 32, "parent_span_id": "b" * 16},
    )

    assert (run.route, run.answer) == ("guide", "1. Do it.")
    assert run.citations == [{"id": 1, "page": 3}]
    assert run.diagnostics == {"retrievals": 4, "sections": 3}
    assert run.events == 6
    assert 0 <= run.first_event_ms <= run.ttft_ms <= run.latency_ms
    sent = _Client.captured
    assert sent["url"] == "http://gateway/invocations"
    assert sent["body"] == {
        "prompt": "How?",
        "knowledgeBaseId": "ABCDE12345",
        "diagnostics": True,
    }
    assert sent["headers"]["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] == "sess"
    assert sent["headers"]["traceparent"] == f"00-{'a' * 32}-{'b' * 16}-01"


async def test_a_run_with_no_answer_text_has_no_ttft(monkeypatch):
    monkeypatch.setattr(
        agent_client.httpx,
        "AsyncClient",
        lambda *a, **k: _Client(_events({"route": "easy"})),
    )

    run = await agent_client.invoke_agent("hi", "ABCDE12345", "s")

    assert run.ttft_ms is None and run.answer == ""


async def test_transient_failures_are_retried_then_succeed(monkeypatch):
    calls = []

    async def flaky(url, body, session_id, *, traceparent=None):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ReadError("reset")
        return agent_client.AgentRun(answer="ok")

    async def no_sleep(_):
        pass

    monkeypatch.setattr(agent_client, "_invoke_once", flaky)
    monkeypatch.setattr(agent_client.asyncio, "sleep", no_sleep)

    assert (await agent_client.invoke_agent("q", "ABCDE12345", "s")).answer == "ok"
    assert len(calls) == 3


async def test_non_retryable_errors_propagate_immediately(monkeypatch):
    async def bad_request(*args, **kwargs):
        request = httpx.Request("POST", "http://x")
        raise httpx.HTTPStatusError(
            "bad", request=request, response=httpx.Response(400, request=request)
        )

    monkeypatch.setattr(agent_client, "_invoke_once", bad_request)

    with pytest.raises(httpx.HTTPStatusError):
        await agent_client.invoke_agent("q", "ABCDE12345", "s")
