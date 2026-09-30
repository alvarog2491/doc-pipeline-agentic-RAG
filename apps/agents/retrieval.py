"""Retrieve passages from one document's Bedrock Knowledge Base."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

import boto3

from excerpts import Passage

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_ID = re.compile(r"[0-9A-Za-z]{10}")

Retriever = Callable[[str, str, int], Awaitable[list[Passage]]]
"""``(knowledge_base_id, query, number_of_results)`` -> passages, best first."""

RETRIEVAL_LOG: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "retrieval_log", default=None
)
"""When set, every ``retrieve`` call of the current run appends ``{query, requested, returned}``.

The list is shared by reference, so it also collects calls made by parallel subagent tasks.
"""

_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        region = os.environ.get("AWS_REGION") or os.environ["AWS_DEFAULT_REGION"]
        _client = boto3.client("bedrock-agent-runtime", region_name=region)
    return _client


def _passages(results: list[dict[str, Any]]) -> list[Passage]:
    passages: list[Passage] = []
    for result in results:
        text = result.get("content", {}).get("text", "")
        if not text:
            continue
        metadata = result.get("metadata", {})
        section = str(metadata.get("section") or "")
        passages.append(
            Passage(
                text=text,
                page=int(metadata.get("page") or 1),
                source=str(metadata.get("source") or ""),
                section="" if section == "-" else section,
            )
        )
    return passages


async def retrieve(
    knowledge_base_id: str, query: str, number_of_results: int
) -> list[Passage]:
    """Run a semantic search against a Knowledge Base.

    Args:
        knowledge_base_id: Bedrock Knowledge Base id of the selected document.
        query: Natural-language search query.
        number_of_results: Maximum number of passages to return.

    Returns:
        Passages ordered by relevance; empty when nothing matches.

    Raises:
        ValueError: If ``knowledge_base_id`` is not a well-formed Bedrock id.
    """
    if not KNOWLEDGE_BASE_ID.fullmatch(knowledge_base_id):
        raise ValueError("knowledge_base_id is not a valid Bedrock Knowledge Base id")
    response = await asyncio.to_thread(
        _get_client().retrieve,
        knowledgeBaseId=knowledge_base_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": number_of_results}
        },
    )
    passages = _passages(response.get("retrievalResults", []))
    if (log := RETRIEVAL_LOG.get()) is not None:
        log.append(
            {"query": query, "requested": number_of_results, "returned": len(passages)}
        )
    return passages
