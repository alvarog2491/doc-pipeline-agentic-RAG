"""Invoke the agent through the AgentCore Gateway and stream its events."""

import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from chat_api.core.config import sigv4_sign

logger = logging.getLogger(__name__)


class AgentCoreResponseError(RuntimeError):
    """The Gateway was unreachable or rejected the request."""


_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=900.0, write=10.0, pool=10.0)
_FEEDBACK_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_STREAM_TIMEOUT)
    return _client


async def close_client() -> None:
    """Close the shared HTTP client."""
    global _client
    client, _client = _client, None
    if client is not None and not client.is_closed:
        await client.aclose()


def _invocations_url() -> str:
    return f"{os.environ['AGENT_GATEWAY_URL'].rstrip('/')}/invocations"


def _signed(session_id: str, body: bytes) -> dict[str, str]:
    return sigv4_sign(
        "POST",
        _invocations_url(),
        body,
        {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        },
    )


async def submit_feedback(
    session_id: str, *, outcome: str, comment: str | None
) -> None:
    """Forward conversation feedback through the Gateway.

    Args:
        session_id: Conversation session receiving the feedback score.
        outcome: ``helpful`` or ``not_helpful``.
        comment: Optional supporting detail.

    Raises:
        AgentCoreResponseError: If the Gateway is unavailable or rejects the request.
    """
    body = json.dumps(
        {"type": "feedback", "outcome": outcome, "comment": comment}
    ).encode()
    try:
        response = await _get_client().post(
            _invocations_url(),
            content=body,
            headers=_signed(session_id, body),
            timeout=_FEEDBACK_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AgentCoreResponseError(
            f"AgentCore Gateway returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise AgentCoreResponseError("AgentCore Gateway could not be reached") from exc


async def stream_chat(
    session_id: str, knowledge_base_id: str, prompt: str
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream the agent's events as they are produced.

    Each yielded mapping is one agent event: ``{"route": ...}``, ``{"progress": ...}``,
    ``{"chunk": ...}`` or ``{"citations": [...]}``. Lines are forwarded the moment they
    arrive, with no buffering, so the first token reaches the client immediately.

    Args:
        session_id: Conversation session id, sent as the AgentCore session header.
        knowledge_base_id: Knowledge Base the question is about.
        prompt: The user's message.

    Yields:
        Decoded agent events.

    Raises:
        AgentCoreResponseError: If the Gateway is unreachable or returns an error status.
    """
    body = json.dumps({"prompt": prompt, "knowledgeBaseId": knowledge_base_id}).encode()
    try:
        async with _get_client().stream(
            "POST",
            _invocations_url(),
            content=body,
            headers=_signed(session_id, body),
            timeout=_STREAM_TIMEOUT,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    yield message
    except httpx.HTTPStatusError as exc:
        raise AgentCoreResponseError(
            f"AgentCore Gateway returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise AgentCoreResponseError("AgentCore Gateway could not be reached") from exc
