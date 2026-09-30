"""Invoke the deployed agent through its production Gateway path and time the stream."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

import httpx
from utils.gateway import resolve_gateway_url
from utils.sigv4 import sigv4_sign

logger = logging.getLogger(__name__)

# One reset among a batch of concurrent invocations is a cold-start or intermediary hiccup,
# so transient transport errors and Gateway 5xx are retried on the same session id.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFFS_S = (2.0, 8.0)
_RETRYABLE_STATUS = frozenset({502, 503, 504})


@dataclass
class AgentRun:
    """Everything one agent turn produced, with client-side timings.

    Attributes:
        answer: Concatenated answer text.
        route: Route the orchestrator chose, or an empty string.
        citations: Citations the runtime resolved for the answer.
        diagnostics: Runtime diagnostics (retrieval count, retrieved excerpts, subagent output).
        ttft_ms: Milliseconds from request start to the first answer chunk.
        latency_ms: Milliseconds from request start to the end of the stream.
        first_event_ms: Milliseconds to the first event of any kind.
        events: Number of stream events received.
    """

    answer: str = ""
    route: str = ""
    citations: list[dict] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    ttft_ms: float | None = None
    latency_ms: float = 0.0
    first_event_ms: float | None = None
    events: int = 0


async def _invoke_once(
    url: str, body: bytes, session_id: str, *, traceparent: str | None = None
) -> AgentRun:
    """Run one Gateway invocation attempt and fold its event stream into an ``AgentRun``."""
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    if traceparent is not None:
        request_headers["traceparent"] = traceparent
    headers = sigv4_sign("POST", url, body, request_headers)

    run = AgentRun()
    chunks: list[str] = []
    started = time.monotonic()
    async with (
        httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=900.0, write=10.0, pool=10.0)
        ) as client,
        client.stream("POST", url, content=body, headers=headers) as response,
    ):
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            elapsed = (time.monotonic() - started) * 1000
            run.events += 1
            if run.first_event_ms is None:
                run.first_event_ms = elapsed
            if isinstance(chunk := message.get("chunk"), str) and chunk:
                if run.ttft_ms is None:
                    run.ttft_ms = elapsed
                chunks.append(chunk)
            elif isinstance(route := message.get("route"), str):
                run.route = route
            elif isinstance(citations := message.get("citations"), list):
                run.citations = citations
            elif isinstance(diagnostics := message.get("diagnostics"), dict):
                run.diagnostics = diagnostics
    run.answer = "".join(chunks)
    run.latency_ms = (time.monotonic() - started) * 1000
    return run


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return isinstance(exc, httpx.TransportError)


async def invoke_agent(
    prompt: str,
    knowledge_base_id: str,
    session_id: str,
    *,
    trace_context: dict[str, str] | None = None,
) -> AgentRun:
    """Invoke the deployed agent through the AgentCore Gateway with diagnostics enabled.

    A transient transport error or Gateway 5xx is retried on the same ``session_id`` with
    backoff; a non-retryable error or the final attempt propagates.

    Args:
        prompt: User message sent to the runtime.
        knowledge_base_id: Knowledge Base of the evaluation document.
        session_id: AgentCore session identifier used for conversation continuity.
        trace_context: Optional upstream trace and parent observation identifiers.

    Returns:
        The timed run.

    Raises:
        httpx.HTTPStatusError: If the Gateway returns an unsuccessful HTTP status.
        httpx.HTTPError: If the request cannot be completed after every attempt.
    """
    url = f"{resolve_gateway_url().rstrip('/')}/invocations"
    body = json.dumps(
        {"prompt": prompt, "knowledgeBaseId": knowledge_base_id, "diagnostics": True}
    ).encode()
    traceparent = None
    if trace_context is not None:
        traceparent = (
            f"00-{trace_context['trace_id']}-{trace_context['parent_span_id']}-01"
        )

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await _invoke_once(url, body, session_id, traceparent=traceparent)
        except Exception as exc:
            if attempt == _MAX_ATTEMPTS or not _is_retryable(exc):
                raise
            backoff = _RETRY_BACKOFFS_S[attempt - 1]
            logger.warning(
                "Gateway invocation attempt %d/%d failed (%s: %s); retrying in %.0fs (session_id=%s)",
                attempt,
                _MAX_ATTEMPTS,
                type(exc).__name__,
                exc,
                backoff,
                session_id,
            )
            await asyncio.sleep(backoff)

    raise AssertionError("unreachable")  # loop either returns or raises
