"""``POST /v1/chat/stream``: stream one agent turn as Server-Sent Events."""

import logging
import uuid
from collections.abc import AsyncIterable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from chat_api.core.config import Settings
from chat_api.core.protocol import (
    ChatRequest,
    Citation,
    CitationsEvent,
    CompletedEvent,
    DeltaEvent,
    ErrorEvent,
    ProgressEvent,
    RouteEvent,
)
from chat_api.services import agentcore, documents, registry

router = APIRouter()
logger = logging.getLogger(__name__)

_ROUTES = {"easy", "hard", "guide"}


def _sse(event: Any) -> ServerSentEvent:
    return ServerSentEvent(
        raw_data=event.model_dump_json(by_alias=True),
        event=event.type,
        id=str(event.sequence),
    )


async def _citations(raw: list[Any], settings: Settings) -> list[Citation]:
    """Turn the agent's citation mappings into citations with presigned page links."""
    citations: list[Citation] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            url = await documents.page_link(
                settings.documents_bucket,
                str(item.get("source", "")),
                int(item["page"]),
                settings.link_ttl_seconds,
            )
            citations.append(
                Citation(
                    id=int(item["id"]),
                    page=int(item["page"]),
                    section=str(item.get("section", "")),
                    url=url,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return citations


async def _events(
    body: ChatRequest, request_id: str, settings: Settings
) -> AsyncIterable[ServerSentEvent]:
    sequence = 0

    def stamp() -> dict[str, Any]:
        nonlocal sequence
        sequence += 1
        return {"request_id": request_id, "sequence": sequence - 1}

    try:
        async for message in agentcore.stream_chat(
            str(body.session_id), body.knowledge_base_id, body.prompt
        ):
            if (route := message.get("route")) in _ROUTES:
                yield _sse(RouteEvent(route=route, **stamp()))
            elif isinstance(progress := message.get("progress"), str) and progress:
                yield _sse(ProgressEvent(text=progress, **stamp()))
            elif isinstance(chunk := message.get("chunk"), str) and chunk:
                yield _sse(DeltaEvent(text=chunk, **stamp()))
            elif isinstance(raw := message.get("citations"), list):
                yield _sse(
                    CitationsEvent(citations=await _citations(raw, settings), **stamp())
                )
        yield _sse(CompletedEvent(**stamp()))
    except agentcore.AgentCoreResponseError:
        logger.exception("Agent invocation failed: request_id=%s", request_id)
        yield _sse(
            ErrorEvent(
                code="agent_unavailable",
                message="The assistant is unavailable. Please try again.",
                **stamp(),
            )
        )
    except Exception:
        logger.exception("Unexpected streaming failure: request_id=%s", request_id)
        yield _sse(
            ErrorEvent(
                code="internal_error",
                message="Something went wrong. Please try again.",
                **stamp(),
            )
        )


async def _require_ready_document(body: ChatRequest, request: Request) -> None:
    """Reject requests for unknown or still-processing documents before streaming starts."""
    settings: Settings = request.app.state.settings
    if not await registry.find_ready(settings.registry_table, body.knowledge_base_id):
        raise HTTPException(
            status_code=404, detail="Knowledge base not found or not ready"
        )


@router.post(
    "/chat/stream",
    response_class=EventSourceResponse,
    dependencies=[Depends(_require_ready_document)],
)
async def stream_chat(
    body: ChatRequest, request: Request
) -> AsyncIterable[ServerSentEvent]:
    """Stream the agent's answer for one message about a selected document.

    Events arrive as the agent produces them: ``route``, ``progress``*, ``delta``*,
    ``citations`` and finally ``completed`` (or ``error``). Every event carries ``requestId``
    and a monotonic ``sequence``. Unknown or unready Knowledge Bases get a 404 before any
    event is sent.

    Args:
        body: Validated chat request.
        request: Incoming request, used to reach application settings.

    Yields:
        Server-sent events, flushed as soon as the agent emits them.
    """
    async for event in _events(body, str(uuid.uuid4()), request.app.state.settings):
        yield event
